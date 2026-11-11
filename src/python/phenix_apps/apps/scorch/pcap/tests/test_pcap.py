import json
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
from phenix_apps.common import utils
from phenix_apps.common.logger import logger
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "pcap")


def test_readme_has_examples():
    assert len(readme_examples()) == 3


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


OLD = "minimega 3.3.0 abc123 2026-01-01"
NEW = "minimega 3.4.0 def456 2026-12-01"
HEADER = ["id", "host", "bridge", "state", "packets", "kdrops", "error", "path"]


class FakeMM:
    """The minimega calls of the pcap component, recorded as tuples. By default
    it is a minimega 3.3.0, which has no per-capture options."""

    def __init__(self, captures=(), version=OLD):
        self.captures, self.calls, self.answer = captures, [], version

    def version(self):
        return [{"Response": self.answer}]

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

    def capture_pcap_vm(self, vm, interface, path, option=None):
        self.calls.append(
            ("capture", vm, interface, option) if option else ("capture", vm, interface)
        )


class NewMM(FakeMM):
    """A minimega 3.4.0: the listing has a header, and a delete answers with the
    final rows. `rows` are dicts that default to a running capture."""

    def __init__(self, rows=(), replies=None):
        super().__init__(version=NEW)
        self.rows, self.replies = list(rows), replies or {}
        self.deleted: list[str] = []

    @staticmethod
    def table(rows):
        return [
            {
                "Header": HEADER,
                "Tabular": [[r.get(h, "") for h in HEADER] for r in rows],
            }
        ]

    def capture(self):
        return self.table(self.rows)

    def capture_pcap_delete_vm(self, vm, interface=None):
        self.calls.append(("delete", vm, interface))
        return self.table(self.replies.get((vm, interface), []))

    def capture_pcap_namespace(self, filename=None, option=None):
        if filename is None:
            return self.table(self.rows)
        self.calls.append(("namespace", Path(filename).name, option))
        return None

    def capture_pcap_delete_namespace(self, ident):
        self.calls.append(("delete-namespace", ident))
        return self.table(self.replies.get(ident, []))


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

    paths, host_of, reported = comp._stop_captures()

    assert mm.calls == [("delete", "aa", 1), *clears]
    assert paths == [tmp_path / "aa-1.pcap"]
    assert host_of == {"aa-1.pcap": "aa"}
    assert reported == {}


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


def modern(mm, base_dir, md, vlans=None):
    comp = component(mm)
    comp.name, comp.base_dir = "pcap", base_dir
    comp._check_run_order = lambda: None
    comp.get_host_and_iface = lambda cfg: (cfg["hostname"], cfg["interface"])
    comp.require_node = lambda hostname: None
    comp.experiment = Box({"status": {"vlans": vlans or {}}})
    comp.config = PCAPMetadata.model_validate(md)
    return comp


def test_start_with_minimega_3_4_passes_options_and_clears_nothing(tmp_path):
    mm = NewMM()
    comp = modern(
        mm,
        tmp_path,
        {
            "filter": "port 80",
            "snaplen": 128,
            "format": "pcapng",
            "vms": [
                {"hostname": "aa"},
                {"hostname": "bb", "filter": "ip proto tcp", "snaplen": 0},
            ],
        },
    )

    comp.start()

    assert mm.calls == [
        ("capture", "aa", 0, "format=pcapng filter='port 80' snaplen=128"),
        ("capture", "bb", 0, "format=pcapng filter='ip proto tcp'"),
    ]


def test_bad_snaplen_fails_before_any_capture_starts(tmp_path):
    mm = NewMM()
    comp = modern(
        mm,
        tmp_path,
        {"vms": [{"hostname": "aa"}, {"hostname": "bb", "snaplen": 5}]},
    )

    with pytest.raises(ValueError, match="snaplen 5 is not from 14 to 65535"):
        comp.start()

    assert mm.calls == []


def test_start_with_an_old_minimega_keeps_the_namespace_wide_options(tmp_path):
    mm = FakeMM([["9", "other"]])
    comp = modern(mm, tmp_path, {"snaplen": 128, "vms": [{"hostname": "aa"}]})

    comp.start()

    assert mm.calls == [
        ("clear", "pcap"),
        ("filter", "'len >= 0'"),
        ("snaplen", 128),
        ("capture", "aa", 0),
        ("filter", "'len >= 0'"),
        ("snaplen", 0),
    ]


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"format": "pcapng"}, "format: pcapng requires minimega 3.4.0 or later"),
        ({"mode": "namespace"}, "mode: namespace requires minimega 3.4.0 or later"),
    ],
)
def test_new_features_fail_clearly_on_an_old_minimega(tmp_path, md, message):
    mm = FakeMM()
    comp = modern(mm, tmp_path, {"vms": [{"hostname": "aa"}], **md}, {"EXP_1": 101})

    with pytest.raises(RuntimeError, match=rf"{message}; the oldest node runs 3\.3\.0"):
        comp.start()

    assert mm.calls == []


def test_unreadable_version_counts_as_an_old_minimega(tmp_path):
    comp = modern(FakeMM(version="dev build"), tmp_path, {"vms": [{"hostname": "aa"}]})

    assert comp.capture_support().available is False
    assert "cannot read the minimega version" in comp.capture_support().reason


def test_the_oldest_node_decides(tmp_path):
    mm = NewMM()
    mm.version = lambda: [{"Response": NEW}, {"Response": OLD}]
    comp = modern(mm, tmp_path, {"vms": [{"hostname": "aa"}]})

    assert comp.capture_support().available is False


def test_the_version_is_asked_once(tmp_path):
    mm = NewMM()
    asked = []
    mm.version = lambda: asked.append(1) or [{"Response": NEW}]
    comp = modern(mm, tmp_path, {"vms": [{"hostname": "aa"}]})

    comp.start()
    comp.capture_support()

    assert asked == [1]


def stopped(tmp_path, mm, md=None, monkeypatch=None):
    comp = modern(mm, tmp_path, md or {"vms": [{"hostname": "aa", "interface": 1}]})
    assert monkeypatch is not None
    monkeypatch.setattr(
        utils, "pcap_capinfos", lambda path: {"File type": "Wireshark - pcap"}
    )
    return comp


def test_stop_adds_minimega_state_and_counters_to_the_metadata(tmp_path, monkeypatch):
    path = tmp_path / "aa-1.pcap"
    path.write_bytes(b"x")
    running = {"id": "4", "state": "running", "packets": "10", "path": str(path)}
    final = {**running, "state": "stopped", "packets": "12", "kdrops": "1"}
    mm = NewMM([running], replies={("aa", 1): [final]})
    comp = stopped(tmp_path, mm, monkeypatch=monkeypatch)

    comp.stop()

    meta = json.loads((tmp_path / "pcap_metadata.json").read_text())
    assert meta["aa-1.pcap"] == {
        "File type": "Wireshark - pcap",
        "minimega_state": "stopped",
        "minimega_packets": 12,
        "minimega_kdrops": 1,
    }
    assert mm.calls == [("delete", "aa", 1)]


def test_stop_gives_minimegas_error_for_a_failed_capture(tmp_path, monkeypatch):
    path = tmp_path / "aa-1.pcap"
    path.write_bytes(b"x")
    failed = {
        "id": "4",
        "state": "failed",
        "error": "tap mega_tap9 removed (VM flushed)",
        "path": str(path),
    }
    comp = stopped(tmp_path, NewMM([failed]), monkeypatch=monkeypatch)

    with pytest.raises(RuntimeError, match=r"VM flushed"):
        comp.stop()


def test_stop_only_warns_for_a_full_capture(tmp_path, monkeypatch):
    path = tmp_path / "aa-1.pcap"
    path.write_bytes(b"x")
    full = {"id": "4", "state": "full", "path": str(path)}
    comp = stopped(tmp_path, NewMM([full]), monkeypatch=monkeypatch)
    warnings: list[str] = []
    sink = logger.add(warnings.append, level="WARNING")

    try:
        comp.stop()
    finally:
        logger.remove(sink)

    assert "is full" in "".join(warnings)


def test_stop_with_minimega_3_4_does_not_clear_other_captures(tmp_path, monkeypatch):
    path = tmp_path / "aa-1.pcap"
    path.write_bytes(b"x")
    mm = NewMM([{"id": "4", "state": "running", "path": str(path)}])
    comp = stopped(tmp_path, mm, monkeypatch=monkeypatch)

    comp.stop()

    assert ("clear", "pcap") not in mm.calls


NAMESPACE = {
    "mode": "namespace",
    "format": "pcapng",
    "filter": "tcp",
    "snaplen": 200,
    "vms": [{"hostname": "aa"}, {"hostname": "bb"}],
}


def test_namespace_mode_starts_one_capture_without_mgmt(tmp_path):
    mm = NewMM()
    vlans = {"MGMT": 200, "OT": 101, "IT": 100}
    comp = modern(mm, tmp_path, NAMESPACE, vlans)

    comp.start()

    assert mm.calls == [
        (
            "namespace",
            "merged.pcapng",
            "format=pcapng vlans=IT,OT vms=aa,bb filter='tcp' snaplen=200",
        )
    ]


def test_namespace_mode_vlans_can_be_given(tmp_path):
    mm = NewMM()
    comp = modern(mm, tmp_path, {**NAMESPACE, "vlans": ["MGMT"]}, {"IT": 100})

    comp.start()

    assert " vlans=MGMT " in mm.calls[0][2]


def test_namespace_mode_needs_a_vlan_besides_mgmt(tmp_path):
    comp = modern(NewMM(), tmp_path, NAMESPACE, {"MGMT": 200})

    with pytest.raises(ValueError, match="no VLAN besides MGMT"):
        comp.start()


def test_namespace_stop_ends_our_capture_and_keeps_its_counters(tmp_path, monkeypatch):
    merged = tmp_path / "merged.pcapng"
    merged.write_bytes(b"x")
    other = {"id": "7", "state": "running", "path": str(tmp_path / "other.pcap")}
    ours = {"id": "3", "state": "running", "path": str(merged), "packets": "5"}
    stream = {"id": "3", "host": "compute1", "state": "running", "path": str(merged)}
    final = {**ours, "state": "stopped", "packets": "9", "kdrops": "0"}
    mm = NewMM([other, ours, stream], replies={"3": [final]})
    comp = stopped(tmp_path, mm, NAMESPACE, monkeypatch)

    comp.stop()

    assert mm.calls == [("delete-namespace", "3")]
    meta = json.loads((tmp_path / "pcap_metadata.json").read_text())
    assert meta["merged.pcapng"]["minimega_packets"] == 9
    assert list(meta) == ["merged.pcapng"]


def test_namespace_stop_fails_when_the_capture_is_gone(tmp_path, monkeypatch):
    comp = stopped(tmp_path, NewMM(), NAMESPACE, monkeypatch)

    with pytest.raises(RuntimeError, match="no minimega namespace capture writes"):
        comp.stop()


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"vlans": ["EXP_1"]}, "vlans: only used with mode: namespace"),
        ({"format": "tiff"}, "format"),
        ({"mode": "all"}, "mode"),
        ({"mode": "namespace", "vlans": []}, "vlans"),
        (
            {"mode": "namespace", "vms": [{"hostname": "aa", "interface": 1}]},
            r"vms\.0\.interface: not used with mode: namespace",
        ),
        (
            {"mode": "namespace", "vms": [{"hostname": "aa", "filter": "tcp"}]},
            r"vms\.0\.filter: not used with mode: namespace",
        ),
        ({"mode": "namespace", "dedupe": False}, "dedupe: not used"),
        (
            {"mode": "namespace", "create_merged_pcap": True},
            "create_merged_pcap: not used",
        ),
    ],
)
def test_bad_mode_metadata_is_rejected(md, message):
    md = {"vms": [{"hostname": "aa"}], **md}
    with pytest.raises(ValueError, match=message):
        parse_metadata(PCAPMetadata, md, "p")


def test_new_fields_default_to_the_old_behavior():
    config = parse_metadata(PCAPMetadata, {"vms": [{"hostname": "aa"}]}, "p")

    assert (config.format, config.mode, config.vlans) == ("pcap", "per_vm", None)


@pytest.mark.parametrize(
    ("fmt", "args", "name"),
    [
        ("pcap", [], "merged.pcap"),
        ("pcapng", ["-F", "pcapng"], "merged.pcapng"),
    ],
)
def test_mergecap_writes_the_chosen_format(tmp_path, monkeypatch, fmt, args, name):
    comp = modern(NewMM(), tmp_path, {"format": fmt, "vms": [{"hostname": "aa"}]})
    comp.config = comp.config.model_copy(update={"merge_timeout": 5.0})
    seen = []

    def fake_run(cmd, timeout):
        seen.append(cmd)
        Path(cmd[2]).write_bytes(b"x")

    monkeypatch.setattr(utils, "run_command", fake_run)

    merged = comp._merge_pcaps([tmp_path / "a.pcap"])

    assert merged == tmp_path / name
    assert seen == [["mergecap", "-w", str(merged), *args, str(tmp_path / "a.pcap")]]
