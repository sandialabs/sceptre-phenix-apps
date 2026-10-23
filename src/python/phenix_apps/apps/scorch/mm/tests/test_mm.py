import subprocess
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.mm.mm import MM, MMMetadata, _capture_file
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_examples_are_valid_and_clean():
    examples = readme_components(README, "mm")
    assert len(examples) == 2

    for cmp in examples:
        _, warnings = validate_metadata(MMMetadata, cmp["metadata"], cmp["name"])
        assert warnings == []


def test_old_forms_still_work():
    md = {
        "start": None,
        "stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}],
        "vms": [
            {
                "hostname": "a",
                "cleanup": None,
                "start": [
                    {"type": "connect", "connect": {"interface": 1, "vlan": 101}},
                    {"type": "stop_capture"},
                ],
            }
        ],
    }
    config, warnings = validate_metadata(MMMetadata, md, "m")

    assert warnings == []
    assert config.start == []
    assert config.vms[0].cleanup == []
    connect = config.vms[0].start[0].connect
    assert connect is not None
    assert (connect.interface, connect.vlan) == (1, 101)


@pytest.mark.parametrize(
    ("md", "warning"),
    [
        (
            {
                "stop": [
                    {
                        "type": "stop_capture",
                        "capture": {"bridge": "p", "filename": "x y"},
                    }
                ]
            },
            "stop.0.capture.filename: unknown key, ignored",
        ),
        (
            {"vms": [{"hostname": "a", "start": [{"type": "start", "connect": {}}]}]},
            "vms.0.start.0.connect: unknown key, ignored",
        ),
    ],
)
def test_fields_a_command_never_read_only_warn(md, warning):
    _, warnings = validate_metadata(MMMetadata, md, "m")
    assert warnings[0].startswith(warning)


@pytest.mark.parametrize("hostname", ["vm[1-3]", "a,b", "*"])
def test_minimega_vm_targets_are_accepted(hostname):
    md = {"vms": [{"hostname": hostname, "start": [{"type": "start"}]}]}
    parse_metadata(MMMetadata, md, "m")


def test_stop_capture_block_is_optional():
    md = {"vms": [{"hostname": "a", "stop": [{"type": "stop_capture"}]}]}
    config = parse_metadata(MMMetadata, md, "m")
    assert config.vms[0].stop[0].capture is None


@pytest.mark.parametrize("capture", [False, ""])
def test_stop_capture_block_must_be_a_mapping(capture):
    md = {
        "vms": [
            {"hostname": "a", "stop": [{"type": "stop_capture", "capture": capture}]}
        ]
    }
    with pytest.raises(ValueError, match="capture"):
        parse_metadata(MMMetadata, md, "m")


@pytest.mark.parametrize("convert", ["maybe", None, {}])
def test_convert_must_be_a_bool(convert):
    cap = {"bridge": "p", "convert": convert}
    md = {"stop": [{"type": "stop_capture", "capture": cap}]}
    with pytest.raises(ValueError, match="convert"):
        parse_metadata(MMMetadata, md, "m")


def test_capture_file_adds_pcap():
    assert _capture_file("c") == "c.pcap"
    assert _capture_file("c.PCAP") == "c.PCAP"


def test_default_capture_name_with_a_vm_pattern_is_refused():
    with pytest.raises(ValueError, match=r"set capture\.filename"):
        _capture_file("vm[1-3]-0-t.pcap", default=True)
    assert _capture_file("vm1-0-t", default=True) == "vm1-0-t.pcap"


@pytest.mark.parametrize(
    ("cap", "field"),
    [
        ({"bridge": "phenix; shell id"}, "bridge"),
        ({"bridge": "phenix", "filename": "cap file.pcap"}, "filename"),
        ({"bridge": "phenix", "filename": "/tmp/x/cap.pcap"}, "filename"),
        ({"bridge": "phenix", "filename": ""}, "filename"),
        ({"bridge": "phenix", "filter": ""}, "filter"),
        ({"bridge": "phenix", "filter": "  "}, "filter"),
        ({"bridge": "phenix", "filter": '"port 80"'}, "filter"),
        ({"bridge": "phenix", "filter": "port 80' quit '"}, "filter"),
        ({"bridge": "phenix", "snaplen": -1}, "snaplen"),
    ],
)
def test_values_spliced_into_minimega_commands_are_checked(cap, field):
    md = {"start": [{"type": "start_capture", "capture": cap}]}
    with pytest.raises(ValueError, match=rf"start\.0\.start_capture\.capture\.{field}"):
        parse_metadata(MMMetadata, md, "m")


class FakeMinimega:
    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


def test_filter_is_quoted_and_reset(tmp_path):
    md = {
        "start": [
            {
                "type": "start_capture",
                "capture": {"bridge": "phenix", "filter": "port 80", "filename": "c"},
            }
        ]
    }
    mm = FakeMinimega()
    component = MM.__new__(MM)
    component.config = parse_metadata(MMMetadata, md, "m")
    component.base_dir = tmp_path
    component.mm = mm

    component.start()

    assert mm.calls == [
        ("capture_pcap_filter", "'port 80'"),
        ("mesh_send", "all", f"shell mkdir -p {tmp_path}"),
        ("capture_pcap_bridge", "phenix", str(tmp_path / "c.pcap")),
        # match-all, never "": minimega drops an empty argument under a namespace
        ("capture_pcap_filter", "'len >= 0'"),
        ("capture_pcap_snaplen", 0),
    ]


def test_vm_start_capture_default_name_is_checked_up_front():
    cap = {"type": "start_capture", "capture": {"interface": 0}}
    md = {"vms": [{"hostname": "vm[1-3]", "start": [cap]}]}
    with pytest.raises(ValueError, match=r"set capture\.filename"):
        parse_metadata(MMMetadata, md, "m")

    cap["capture"]["filename"] = "c"
    parse_metadata(MMMetadata, md, "m")
    md["vms"][0]["hostname"] = "vm1"
    del cap["capture"]["filename"]
    parse_metadata(MMMetadata, md, "m")


def _component(tmp_path, md, mm=None):
    component = MM.__new__(MM)
    component.config = parse_metadata(MMMetadata, md, "m")
    component.base_dir = tmp_path / "run"
    component.base_dir.mkdir()
    component.root_dir = tmp_path
    component.mm = mm or FakeMinimega()
    return component


@pytest.mark.parametrize("filter_", ["a\\b", "a#b", "it's", 'a"b', "a\nb"])
def test_filter_minimega_would_misread_is_refused(filter_):
    cap = {"bridge": "phenix", "filter": filter_}
    md = {"start": [{"type": "start_capture", "capture": cap}]}
    with pytest.raises(ValueError, match="filter"):
        parse_metadata(MMMetadata, md, "m")


@pytest.mark.parametrize(("iface", "expect"), [(1, 1), (None, None)])
def test_vm_stop_capture_can_target_an_interface(tmp_path, iface, expect):
    cap = {} if iface is None else {"interface": iface}
    md = {
        "vms": [{"hostname": "a", "stop": [{"type": "stop_capture", "capture": cap}]}]
    }
    component = _component(tmp_path, md)
    component.stop()
    assert ("capture_pcap_delete_vm", "a", expect) in component.mm.calls


def test_unstopped_capture_only_warns(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("phenix_apps.apps.scorch.mm.mm.logger.warning", warnings.append)
    start = {"type": "start_capture", "capture": {"bridge": "phenix", "filename": "c"}}
    vm_start = {"type": "start_capture", "capture": {"interface": 0, "filename": "d"}}
    md = {
        "start": [start],
        "vms": [
            {"hostname": "a", "start": [vm_start], "stop": [{"type": "stop_capture"}]}
        ],
    }
    _component(tmp_path, md).start()
    assert len(warnings) == 1
    assert "bridge phenix" in warnings[0]  # the VM one is stopped by the stop stage


class ConvertMinimega(FakeMinimega):
    def __init__(self, running=()):
        super().__init__()
        self.running = running

    def file_status(self):
        return [{"Tabular": []}]

    def capture(self):
        return [{"Tabular": [["b", "pcap", "", "", "", p] for p in self.running]}]


def _convert_md():
    cap = {"bridge": "phenix", "convert": True}
    return {
        "transfer_poll_interval": 0.001,
        "stop": [{"type": "stop_capture", "capture": cap}],
    }


def test_convert_skips_running_and_failed_captures(tmp_path, monkeypatch):
    component = _component(tmp_path, _convert_md())
    run = component.base_dir
    for name in ("done", "live", "bad"):
        (run / f"{name}.pcap").write_bytes(b"x")
    (run / "done.pcap.jsonl").write_text("old")
    component.mm = ConvertMinimega(running=[str(run / "live.pcap")])

    def fake_run(cmd, stdout, **_):
        stdout.write(b"{}")
        return subprocess.CompletedProcess(cmd, 1 if cmd[2].endswith("bad.pcap") else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    errors = []
    monkeypatch.setattr("phenix_apps.apps.scorch.mm.mm.logger.error", errors.append)

    component.stop()  # a failed conversion is logged, never raised

    assert sorted(p.name for p in run.iterdir()) == [
        "bad.pcap",
        "done.pcap",
        "done.pcap.jsonl",
        "live.pcap",
    ]
    assert (run / "done.pcap.jsonl").read_text() == "old"
    assert len(errors) == 1
    assert "bad.pcap" in errors[0]


def test_convert_timeout_is_logged_not_raised(tmp_path, monkeypatch):
    md = _convert_md() | {"convert_timeout": 0.01}
    component = _component(tmp_path, md)
    component.mm.file_status = lambda: [{"Tabular": [["f"]]}]
    errors = []
    monkeypatch.setattr("phenix_apps.apps.scorch.mm.mm.logger.error", errors.append)

    component.stop()

    assert "not done" in errors[0]
