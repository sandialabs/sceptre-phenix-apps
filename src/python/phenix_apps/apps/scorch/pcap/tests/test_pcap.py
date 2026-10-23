from pathlib import Path

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.pcap.pcap import (
    PCAP,
    PCAPMetadata,
    dos_targets_for_run,
    run_order_warnings,
    split_by_host,
)
from phenix_apps.common.logger import logger
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "pcap")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(PCAPMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_readme_filebeat_input_matches_the_output():
    (cmp,) = [c for c in readme_examples() if "filebeat.inputs" in c["metadata"]]
    (fb_input,) = cmp["metadata"]["filebeat.inputs"]

    # convert_to_json writes <host>-<iface>.jsonl
    assert fb_input["paths"] == ["*.jsonl"]
    # a drop_event without a condition would drop every event
    (drop,) = [p for p in fb_input["processors"] if "drop_event" in p]
    assert drop == {"drop_event": {"when": {"has_fields": ["scorch.pcap.index._type"]}}}


def test_defaults_match_the_old_code():
    config = parse_metadata(PCAPMetadata, {"vms": [{"hostname": "aa"}]}, "p")

    assert config.vms[0].interface == 0
    assert config.dedupe is True
    assert config.create_merged_pcap is False
    assert config.convert_to_json is False
    assert config.filter is None
    assert config.snaplen is None
    assert config.merge_timeout == 60.0
    assert config.tshark_timeout == 120.0


def test_convert_to_json_old_name_is_a_deprecated_alias():
    logged: list[str] = []
    sink = logger.add(logged.append, level="WARNING")
    md = {"vms": [{"hostname": "aa"}], "convertToJSON": True}

    try:
        config, warnings = validate_metadata(PCAPMetadata, md, "p")
    finally:
        logger.remove(sink)

    assert config.convert_to_json is True
    assert warnings == []
    assert "convertToJSON' is deprecated" in "".join(logged)
    # the new name wins when both are given
    both = {**md, "convert_to_json": False}
    assert parse_metadata(PCAPMetadata, both, "p").convert_to_json is False


@pytest.mark.parametrize("interface", [0, 1, "eth1"])
def test_interface_forms(interface):
    md = {"vms": [{"hostname": "aa", "interface": interface}]}
    assert parse_metadata(PCAPMetadata, md, "p").vms[0].interface == interface


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({}, "vms: Field required"),
        ({"vms": [{"hostname": "aa"}], "snaplen": -1}, "snaplen"),
        ({"vms": [{"hostname": "aa"}], "filter": "port 22' or '1"}, "filter"),
        ({"vms": [{"hostname": "a;reboot"}]}, r"vms\.0\.hostname"),
        ({"vms": [{"hostname": "aa", "interface": -1}]}, r"vms\.0\.interface"),
        ({"vms": [{"hostname": "aa", "interface": "x" * 16}]}, r"vms\.0\.interface"),
        ({"vms": [{"hostname": "aa"}], "snaplen": "1500"}, "snaplen"),
        ({"vms": []}, "vms: List should have at least 1 item"),
        (
            {"vms": [{"hostname": "aa"}, {"hostname": "aa", "interface": 0}]},
            "captured more than once: aa 0",
        ),
        ({"vms": [{"hostname": "aa"}], "filter": 80}, "filter"),
        ({"vms": [{"hostname": "aa"}], "filter": "  "}, "filter"),
        ({"vms": [{"hostname": "aa"}], "convert_to_json": None}, "convert_to_json"),
        ({"vms": [{"hostname": "aa"}], "dedupe": "maybe"}, "dedupe"),
        ({"vms": [{"hostname": "aa"}], "merge_timeout": 0}, "merge_timeout"),
        ({"vms": [{"hostname": "aa"}], "tshark_timeout": -1}, "tshark_timeout"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(PCAPMetadata, md, "p")


def test_unknown_vm_key_only_warns():
    md = {"vms": [{"hostname": "aa", "iface": "eth1"}]}
    _, warnings = validate_metadata(PCAPMetadata, md, "p")

    assert warnings == [
        "vms.0.iface: unknown key, ignored. Fix: remove it (did you mean 'interface'?)"
    ]


def test_split_by_host_matches_whole_hostnames():
    paths = [Path("load1-0.pcap"), Path("load10-0.pcap"), Path("load1-a-0.pcap")]
    host_of = {
        "load1-0.pcap": "load1",
        "load10-0.pcap": "load10",
        "load1-a-0.pcap": "load1-a",
    }

    targets, others = split_by_host(paths, host_of, ["load1"])

    assert targets == [Path("load1-0.pcap")]
    assert others == [Path("load10-0.pcap"), Path("load1-a-0.pcap")]


def test_dos_targets_only_from_a_disruption_in_this_run():
    comps = [
        Box(
            name=n,
            type="disruption",
            metadata={"current_disruption": d, "dos": {"targets": [{"hostname": h}]}},
        )
        for n, d, h in [("base", "baseline", "x"), ("dos", "dos", "load5")]
    ]

    assert dos_targets_for_run(comps, {"start": ["base"], "stop": []}) == []
    assert dos_targets_for_run(comps, {"start": ["base", "dos"]}) == ["load5"]
    assert dos_targets_for_run(comps, {"loop": {"start": ["dos"]}}) == ["load5"]
    assert dos_targets_for_run(comps, {"start": ["other"]}) == []


def test_dos_targets_loop_null_and_nested_loops():
    comp = Box(
        name="dos",
        type="disruption",
        metadata={"current_disruption": "dos", "dos": {"targets": [{"hostname": "x"}]}},
    )

    assert dos_targets_for_run([comp], {"start": ["dos"], "loop": None}) == ["x"]
    assert dos_targets_for_run([comp], {"loop": None}) == []
    nested = {"loop": {"start": [], "loop": {"start": ["dos"]}}}
    assert dos_targets_for_run([comp], nested) == ["x"]


def test_run_order_warnings():
    comps = [Box(name="pcap"), Box(name="c", type="collector")]

    ok = {"start": ["pcap"], "stop": ["pcap", "c"]}
    assert run_order_warnings("pcap", comps, ok) == []
    assert run_order_warnings("pcap", comps, {"loop": {**ok}}) == []

    (w,) = run_order_warnings("pcap", comps, {"start": ["pcap"], "stop": ["c", "pcap"]})
    assert "collector ['c'] runs before 'pcap'" in w
    (w,) = run_order_warnings(
        "pcap", comps, {"start": [], "stop": ["pcap"], "loop": None}
    )
    assert "not in a 'start' stage list" in w
    assert len(run_order_warnings("pcap", comps, {})) == 2


class FakeMM:
    def __init__(self, captures):
        self.captures, self.calls = captures, []

    def capture(self):
        return [{"Tabular": self.captures}]

    def capture_pcap_delete_vm(self, vm, interface=None):
        self.calls.append(("delete", vm, interface))

    def clear_capture(self, kind):
        self.calls.append(("clear", kind))

    def capture_pcap_filter(self, bpf):
        self.calls.append(("filter", bpf))

    def capture_pcap_snaplen(self, size):
        self.calls.append(("snaplen", size))

    def capture_pcap_vm(self, vm, interface, path):
        self.calls.append(("capture", vm, interface))


def component(mm):
    comp = object.__new__(PCAP)
    comp.mm = mm
    return comp


def test_active_captures_lists_each_row():
    mm = FakeMM([["1", "vm", "a-0"], ["2", "bridge", "b"]])
    assert component(mm)._active_captures() == ["1 vm a-0", "2 bridge b"]


@pytest.mark.parametrize(
    ("left", "clears"), [([], [("clear", "pcap")]), ([["9", "other"]], [])]
)
def test_stop_ends_only_our_interface_and_clears_only_when_idle(left, clears, tmp_path):
    mm = FakeMM(left)
    comp = component(mm)
    comp.base_dir = tmp_path
    comp.config = PCAPMetadata.model_validate(
        {"vms": [{"hostname": "aa", "interface": 1}]}
    )
    comp.get_host_and_iface = lambda cfg: (cfg["hostname"], cfg["interface"])

    paths, host_of = comp._stop_captures()

    assert mm.calls == [("delete", "aa", 1), *clears]
    assert paths == [tmp_path / "aa-1.pcap"]
    assert host_of == {"aa-1.pcap": "aa"}


def test_start_applies_per_vm_options_then_resets_them(tmp_path):
    mm = FakeMM([])
    comp = component(mm)
    comp.name, comp.base_dir = "pcap", tmp_path
    comp._check_run_order = lambda: None
    comp.get_host_and_iface = lambda cfg: (cfg["hostname"], cfg["interface"])
    comp.config = PCAPMetadata.model_validate(
        {
            "filter": "port 80",
            "snaplen": 128,
            "vms": [
                {"hostname": "aa"},
                {"hostname": "bb", "filter": "ip proto tcp", "snaplen": 0},
            ],
        }
    )

    comp.start()

    assert mm.calls == [
        ("clear", "pcap"),
        ("filter", "'port 80'"),
        ("snaplen", 128),
        ("capture", "aa", 0),
        ("filter", "'ip proto tcp'"),
        ("snaplen", 0),
        ("capture", "bb", 0),
        # reset: a match-all filter (never "", which minimega drops under a
        # namespace) and minimega's default snaplen
        ("filter", "'len >= 0'"),
        ("snaplen", 0),
    ]


@pytest.mark.parametrize("bad", ["a\\b", "a#b", "it's", 'say "x"', "a\nb"])
def test_filter_minimega_would_misread_is_rejected(bad):
    with pytest.raises(ValidationError):
        PCAPMetadata.model_validate({"vms": [{"hostname": "aa"}], "filter": bad})
