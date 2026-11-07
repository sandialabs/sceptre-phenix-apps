import subprocess
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.mm.mm import MM, MMMetadata, _capture_file
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_examples_are_valid_and_clean():
    examples = readme_components(README, "mm")
    assert len(examples) == 3

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


OLD = "minimega 3.3.0 abc123 2026-01-01"
NEW = "minimega 3.4.0 def456 2026-12-01"
HEADER = [
    "bridge",
    "type",
    "interface",
    "mode",
    "compress",
    "id",
    "host",
    "state",
    "packets",
    "kdrops",
    "error",
    "path",
]


class FakeMinimega:
    """Records every call as (name, *args), with the keyword arguments as a
    last dict. By default it is a minimega 3.3.0, which has no capture options."""

    def __init__(self, version=OLD, rows=(), replies=None):
        self.calls: list[tuple] = []
        self.answer, self.rows, self.replies = version, list(rows), replies or {}

    def version(self):
        return [{"Response": self.answer}]

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, *args, *([kwargs] if kwargs else [])))

        return call

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

    def capture_pcap_namespace(self, filename=None, option=None):
        if filename is None:
            return self.table(self.rows)
        self.calls.append(("capture_pcap_namespace", Path(filename).name, option))
        return None

    def capture_pcap_delete_id(self, ident):
        self.calls.append(("capture_pcap_delete_id", ident))
        return self.table(self.replies.get(ident, []))

    def capture_pcap_delete_namespace(self, ident):
        self.calls.append(("capture_pcap_delete_namespace", ident))
        return self.table(self.replies.get(ident, []))


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
        super().__init__(rows=[{"type": "pcap", "path": p} for p in running])

    def file_status(self):
        return [{"Tabular": []}]


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


def _modern(tmp_path, md, rows=(), replies=None, vlans=None):
    mm = FakeMinimega(NEW, rows, replies)
    component = _component(tmp_path, md, mm)
    component.base_dir = tmp_path / "cmp" / "loop-1"
    component.base_dir.mkdir(parents=True)
    component.exp_name = "exp1"
    component.experiment = Box({"status": {"vlans": vlans or {}}})
    return component


def _bridge_start(**cap):
    return {
        "start": [{"type": "start_capture", "capture": {"bridge": "phenix", **cap}}]
    }


def test_capture_file_adds_the_extension_of_the_format():
    assert _capture_file("c", "pcapng") == "c.pcapng"
    assert _capture_file("c.PCAPNG", "pcapng") == "c.PCAPNG"
    assert _capture_file("c", "pcap") == "c.pcap"
    assert _capture_file("vm1-0-t", "pcapng", default=True) == "vm1-0-t.pcapng"


@pytest.mark.parametrize(
    ("cap", "message"),
    [
        ({"format": "pcapng", "filename": "c.pcap"}, "ends in .pcap"),
        ({"format": "pcap", "filename": "c.pcapng"}, "ends in .pcapng"),
        ({"format": "tiff"}, "format"),
    ],
)
def test_format_must_match_the_file_name(cap, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(MMMetadata, _bridge_start(**cap), "m")


def test_bridge_capture_with_minimega_3_4_passes_options_and_sets_nothing(tmp_path):
    component = _modern(
        tmp_path, _bridge_start(filter="port 80", snaplen=100, filename="c")
    )

    component.start()

    assert component.mm.calls == [
        (
            "capture_pcap_bridge",
            "phenix",
            str(tmp_path / "cmp" / "loop-1" / "c.pcap"),
            {"option": "format=pcap filter='port 80' snaplen=100"},
        )
    ]


def test_a_pcapng_file_name_picks_the_format(tmp_path):
    component = _modern(tmp_path, _bridge_start(filename="c.pcapng"))

    component.start()

    (call,) = component.mm.calls
    assert call[2].endswith("c.pcapng")
    assert call[3] == {"option": "format=pcapng"}


def test_vm_capture_with_minimega_3_4_passes_options_and_makes_no_folder(tmp_path):
    cap = {"interface": 1, "filename": "d", "format": "pcapng", "snaplen": 64}
    md = {
        "vms": [{"hostname": "a", "start": [{"type": "start_capture", "capture": cap}]}]
    }
    component = _modern(tmp_path, md)

    component.start()

    assert component.mm.calls == [
        (
            "capture_pcap_vm",
            "a",
            "1",
            str(tmp_path / "cmp" / "loop-1" / "d.pcapng"),
            {"option": "format=pcapng snaplen=64"},
        )
    ]


def test_pcapng_fails_before_any_command_on_an_old_minimega(tmp_path):
    md = _bridge_start(format="pcapng")
    md["vms"] = [{"hostname": "a", "start": [{"type": "start"}]}]
    component = _component(tmp_path, md)

    with pytest.raises(RuntimeError, match=r"format: pcapng requires minimega 3\.4\.0"):
        component.start()

    assert component.mm.calls == []


def test_bridge_stop_with_an_old_minimega_deletes_the_bridge(tmp_path):
    md = {"stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}]}
    component = _component(tmp_path, md)

    component.stop()

    assert ("capture_pcap_delete_bridge", "phenix") in component.mm.calls


def _row(tmp_path, ident, name, **extra):
    return {
        "bridge": "phenix",
        "type": "pcap",
        "id": ident,
        "state": "running",
        "path": str(tmp_path / name),
        **extra,
    }


def test_bridge_stop_with_minimega_3_4_ends_only_this_components_captures(tmp_path):
    rows = [
        _row(tmp_path, "1", "cmp/loop-1/a.pcap"),
        _row(tmp_path, "2", "cmp2/b.pcap"),
        _row(tmp_path, "3", "cmp/loop-1/vm.pcap", interface="web:0"),
        {**_row(tmp_path, "4", "cmp/loop-1/c.pcap"), "bridge": "other"},
    ]
    md = {"stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}]}
    component = _modern(tmp_path, md, rows)

    component.stop()

    assert component.mm.calls == [
        ("capture_pcap_delete_id", "1"),
        ("file_get", "cmp/loop-1"),
    ]


def test_bridge_stop_finds_a_capture_started_in_another_loop(tmp_path):
    rows = [_row(tmp_path, "1", "cmp/loop-2/a.pcap")]
    md = {"stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}]}
    component = _modern(tmp_path, md, rows)
    component.base_dir = tmp_path / "cmp" / "loop-3"

    component.stop()

    assert ("capture_pcap_delete_id", "1") in component.mm.calls


def test_bridge_stop_with_none_of_ours_running_is_an_error(tmp_path):
    rows = [_row(tmp_path, "1", "cmp2/a.pcap")]
    md = {"stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}]}

    with pytest.raises(RuntimeError, match="no pcap capture of this component"):
        _modern(tmp_path, md, rows).stop()


def test_bridge_stop_with_minimega_3_4_reports_a_failed_capture(tmp_path):
    rows = [_row(tmp_path, "1", "cmp/loop-1/a.pcap")]
    failed = _row(tmp_path, "1", "cmp/loop-1/a.pcap", state="failed", error="disk full")
    md = {"stop": [{"type": "stop_capture", "capture": {"bridge": "phenix"}}]}
    component = _modern(tmp_path, md, rows, {"1": [failed]})

    with pytest.raises(RuntimeError, match=r"unable to stop .*disk full"):
        component.stop()


NAMESPACE_START = {
    "type": "start_namespace_capture",
    "capture": {"filename": "all", "vms": ["aa", "bb"], "format": "pcapng"},
}


def test_namespace_capture_leaves_out_mgmt_and_takes_the_options(tmp_path):
    md = {"start": [NAMESPACE_START]}
    component = _modern(tmp_path, md, vlans={"MGMT": 1, "EXP_1": 101, "EXP_2": 102})

    component.start()

    assert component.mm.calls == [
        (
            "capture_pcap_namespace",
            "all.pcapng",
            "format=pcapng vlans=EXP_1,EXP_2 vms=aa,bb",
        )
    ]


def test_namespace_capture_takes_vlans_bridges_and_a_filter(tmp_path):
    cap = {"vlans": ["EXP_1"], "bridges": ["phenix"], "filter": "udp", "snaplen": 90}
    md = {"start": [{"type": "start_namespace_capture", "capture": cap}]}
    component = _modern(tmp_path, md)

    component.start()

    (call,) = component.mm.calls
    assert call[1].startswith("exp1-")
    assert call[1].endswith(".pcap")
    assert call[2] == ("format=pcap vlans=EXP_1 bridges=phenix filter='udp' snaplen=90")


def test_namespace_commands_fail_before_any_command_on_an_old_minimega(tmp_path):
    md = {"start": [NAMESPACE_START]}
    component = _component(tmp_path, md)
    component.experiment = Box({"status": {"vlans": {"EXP_1": 101}}})

    with pytest.raises(
        RuntimeError, match=r"start_namespace_capture requires minimega 3\.4\.0"
    ):
        component.start()

    assert component.mm.calls == []


def test_namespace_stop_ends_our_summary_row_and_does_not_wait_for_a_transfer(tmp_path):
    rows = [
        _row(tmp_path, "5", "cmp/loop-1/all.pcapng", bridge=""),
        _row(tmp_path, "5", "cmp/loop-1/all.pcapng", bridge="phenix", host="compute1"),
        _row(tmp_path, "6", "cmp2/x.pcapng", bridge=""),
    ]
    md = {"stop": [{"type": "stop_namespace_capture"}]}
    component = _modern(tmp_path, md, rows)

    component.stop()

    assert component.mm.calls == [("capture_pcap_delete_namespace", "5")]


def test_namespace_stop_reports_a_failed_capture(tmp_path):
    rows = [_row(tmp_path, "5", "cmp/loop-1/all.pcapng", bridge="")]
    failed = {**rows[0], "state": "failed", "error": "head lost a member"}
    md = {"stop": [{"type": "stop_namespace_capture"}]}
    component = _modern(tmp_path, md, rows, {"5": [failed]})

    with pytest.raises(RuntimeError, match="head lost a member"):
        component.stop()


def test_namespace_stop_with_nothing_running_is_an_error(tmp_path):
    md = {"stop": [{"type": "stop_namespace_capture"}]}

    with pytest.raises(RuntimeError, match="no namespace capture of this component"):
        _modern(tmp_path, md).stop()


def test_namespace_convert_skips_the_transfer_wait_and_a_running_pcapng(
    tmp_path, monkeypatch
):
    md = {"stop": [{"type": "stop_namespace_capture", "capture": {"convert": True}}]}
    component = _modern(
        tmp_path, md, [_row(tmp_path, "5", "cmp/loop-1/all.pcapng", bridge="")]
    )
    run = component.base_dir
    (run / "done.pcapng").write_bytes(b"x")
    (run / "all.pcapng").write_bytes(b"x")
    component.mm.file_status = lambda: pytest.fail("no transfer to wait for")
    component.mm.replies["5"] = []
    converted = []

    def fake_run(cmd, stdout, **_):
        converted.append(cmd[2])
        stdout.write(b"{}")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    component.mm.rows = [_row(tmp_path, "5", "cmp/loop-1/all.pcapng", bridge="")]
    original = component.mm.capture_pcap_delete_namespace

    def delete(ident):
        component.mm.rows = []
        return original(ident)

    component.mm.capture_pcap_delete_namespace = delete

    component.stop()

    assert sorted(Path(c).name for c in converted) == ["all.pcapng", "done.pcapng"]
    assert (run / "done.pcapng.jsonl").is_file()
    assert not any(c[0] == "file_get" for c in component.mm.calls)


def test_unstopped_namespace_capture_only_warns(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("phenix_apps.apps.scorch.mm.mm.logger.warning", warnings.append)

    _component(tmp_path, {"start": [NAMESPACE_START]})._warn_unstopped_captures("start")

    assert len(warnings) == 1
    assert "the namespace" in warnings[0]


def test_namespace_start_alone_is_valid_and_stop_needs_no_block():
    md = {
        "start": [{"type": "start_namespace_capture"}],
        "stop": [{"type": "stop_namespace_capture"}],
    }
    config = parse_metadata(MMMetadata, md, "m")

    assert config.start[0].capture.vlans is None
    assert config.stop[0].capture.convert is False


@pytest.mark.parametrize(
    ("cap", "field"),
    [
        ({"vlans": []}, "vlans"),
        ({"vlans": ["a b"]}, "vlans"),
        ({"vms": ["x;y"]}, "vms"),
        ({"bridges": ["a" * 16]}, "bridges"),
        ({"filter": "it's"}, "filter"),
        ({"filename": "a/b"}, "filename"),
    ],
)
def test_namespace_capture_values_are_checked(cap, field):
    md = {"start": [{"type": "start_namespace_capture", "capture": cap}]}
    with pytest.raises(ValueError, match=rf"capture\.{field}"):
        parse_metadata(MMMetadata, md, "m")


def test_vm_stop_with_minimega_3_4_reports_a_failed_capture(tmp_path):
    md = {"vms": [{"hostname": "a", "stop": [{"type": "stop_capture"}]}]}
    failed = _row(tmp_path, "1", "cmp/loop-1/a.pcap", state="failed", error="no disk")
    component = _modern(tmp_path, md)
    component.mm.capture_pcap_delete_vm = lambda host, iface: component.mm.table(
        [failed]
    )

    with pytest.raises(RuntimeError, match=r"unable to stop .* on vm a: .*no disk"):
        component.stop()
