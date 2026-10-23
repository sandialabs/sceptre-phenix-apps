import re
import subprocess
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.tcpdump.tcpdump import TCPDump, TCPDumpMetadata
from phenix_apps.common.logger import logger
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


@pytest.fixture
def caplog_loguru():
    """Returns a function giving everything logged so far."""

    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG", format="{level}: {message}")
    yield lambda: "\n".join(lines)
    logger.remove(sink)


def readme_examples() -> list[dict]:
    return readme_components(README, "tcpdump")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(TCPDumpMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_readme_filebeat_input_matches_the_output():
    (cmp,) = [c for c in readme_examples() if "filebeat.inputs" in c["metadata"]]
    (fb_input,) = cmp["metadata"]["filebeat.inputs"]

    assert fb_input["paths"] == ["*.pcap.jsonl"]
    (drop,) = [p for p in fb_input["processors"] if "drop_event" in p]
    assert drop == {
        "drop_event": {"when": {"has_fields": ["scorch.tcpdump.index._type"]}}
    }


def test_guest_text_is_stripped():
    md = {"vms": [{"hostname": "aa", "iface": "e", "filter": "port 80\n"}]}
    assert parse_metadata(TCPDumpMetadata, md, "t").vms[0].filter == "port 80"


def test_defaults():
    md = {"vms": [{"hostname": "aa", "iface": "eth0.1"}]}
    config = parse_metadata(TCPDumpMetadata, md, "t")

    assert config.convert_to_json is False
    assert (config.vms[0].options, config.vms[0].filter) == ("", "")


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({}, "vms: Field required"),
        ({"vms": []}, "vms: List should have at least 1 item"),
        ({"vms": [{"iface": "eth0"}]}, r"vms\.0\.hostname"),
        ({"vms": [{"hostname": "aa"}]}, r"vms\.0\.iface"),
        ({"vms": [{"hostname": "aa", "iface": "eth0;id"}]}, r"vms\.0\.iface"),
        (
            {
                "vms": [
                    {"hostname": "aa", "iface": "e"},
                    {"hostname": "aa", "iface": "e"},
                ]
            },
            "captured more than once: aa e",
        ),
        (
            {"vms": [{"hostname": "aa", "iface": "e"}], "convert_to_json": None},
            "convert_to_json",
        ),
        ({"vms": [{"hostname": "aa", "iface": "e", "filter": None}]}, "filter"),
        ({"vms": [{"hostname": "aa", "iface": "e", "options": None}]}, "options"),
        ({"vms": [{"hostname": "aa", "iface": "e", "filter": 80}]}, "filter"),
        ({"vms": [{"hostname": "aa", "iface": "e", "filter": "a'b"}]}, "filter"),
        ({"vms": [{"hostname": "a", "iface": "e"}]}, r"vms\.0\.hostname"),
        ({"vms": [{"hostname": "aa", "iface": "eth0:1"}]}, r"vms\.0\.iface"),
        (
            {"vms": [{"hostname": "aa", "iface": "e"}], "convert_to_json": "true"},
            "convert",
        ),
        (
            {"vms": [{"hostname": "aa", "iface": "e"}], "convertTimeout": 0},
            "convertTimeout",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(TCPDumpMetadata, md, "t")


def test_unknown_vm_key_only_warns():
    md = {"vms": [{"hostname": "aa", "iface": "eth0", "option": "-c 5"}]}
    _, warnings = validate_metadata(TCPDumpMetadata, md, "tcpdump")

    assert warnings == [
        "vms.0.option: unknown key, ignored. Fix: remove it (did you mean 'options'?)"
    ]


def test_convert_to_json_old_name_is_a_deprecated_alias(caplog_loguru):
    md = {"vms": [{"hostname": "aa", "iface": "e"}], "convertToJSON": True}

    config, warnings = validate_metadata(TCPDumpMetadata, md, "t")

    assert config.convert_to_json is True
    assert warnings == []
    assert "convertToJSON' is deprecated" in caplog_loguru()
    # the new name wins when both are given
    both = {**md, "convert_to_json": False}
    assert parse_metadata(TCPDumpMetadata, both, "t").convert_to_json is False


def test_convert_timeout_default():
    md = {"vms": [{"hostname": "aa", "iface": "e"}]}
    assert parse_metadata(TCPDumpMetadata, md, "t").convertTimeout == 600.0


class FakeMinimega:
    """Records the cc filter in force for every command."""

    def __init__(self):
        self.filter = ""
        self.log: list[tuple[str, str]] = []

    def cc_filter(self, f):
        self.filter = f

    def clear_cc_filter(self):
        self.filter = ""

    def cc_exec(self, cmd):
        self.log.append((self.filter, cmd))

    def cc_background(self, cmd):
        self.log.append((self.filter, cmd))


def make_component(md, tmp_path, monkeypatch, scorch=None, exec_results=None):
    """A TCPDump with a fake minimega. exec_results maps a command prefix to the
    mm_exec_wait result; other commands succeed."""

    mm = FakeMinimega()
    component = TCPDump.__new__(TCPDump)
    component.name = "t"
    component.run = 0
    component.base_dir = tmp_path
    component.config = parse_metadata(TCPDumpMetadata, md, "t")
    component.mm = mm
    component.root_dir = tmp_path
    component.exp_name = "exp"
    (tmp_path / "exp").mkdir()
    component.extract_app = lambda _: Box({"metadata": scorch or {}})
    waited: list[tuple[str, str]] = []
    sent: dict[str, str] = {}
    component.sent = sent

    def exec_wait(mm_, vm, cmd):
        waited.append((vm, cmd))
        for prefix, res in (exec_results or {}).items():
            if cmd.startswith(prefix):
                return res
        return {"stdout": "ok", "stderr": None, "exitcode": 0}

    monkeypatch.setattr("phenix_apps.common.utils.mm_exec_wait", exec_wait)

    def send_wait(mm_, vm, src, exp_name):
        sent[Path(src).name] = Path(src).read_text()

    monkeypatch.setattr("phenix_apps.common.utils.mm_cc_send_wait", send_wait)
    monkeypatch.setattr("phenix_apps.common.utils.mm_recv", lambda *a: None)
    monkeypatch.setattr(
        "phenix_apps.common.utils.mm_cc_filter_vm",
        lambda mm_, vm: mm_.cc_filter(f"uuid=of-{vm}"),
    )
    return component, mm, waited


MD = {
    "vms": [
        {"hostname": "aa", "iface": "eth0", "options": "-c 5", "filter": "(port 80)"},
        {"hostname": "bb", "iface": "eth1"},
    ]
}


def test_start_and_stop_target_each_vm_by_uuid(monkeypatch, tmp_path):
    component, mm, _ = make_component(MD, tmp_path, monkeypatch)

    component.start()
    assert mm.log == [
        ("uuid=of-aa", "ip link set eth0 up"),
        ("uuid=of-aa", "bash /tmp/miniccc/files/exp/tcpdump_aa_eth0.sh"),
        ("uuid=of-bb", "ip link set eth1 up"),
        ("uuid=of-bb", "bash /tmp/miniccc/files/exp/tcpdump_bb_eth1.sh"),
    ]
    assert component.sent == {
        "tcpdump_aa_eth0.sh": "#!/bin/bash\necho $$ > /dump-eth0.pid\n"
        "exec tcpdump -c 5 -i eth0 -U -w /dump-eth0.pcap '(port 80)' "
        "2> /dump-eth0.err\n",
        "tcpdump_bb_eth1.sh": "#!/bin/bash\necho $$ > /dump-eth1.pid\n"
        "exec tcpdump -i eth1 -U -w /dump-eth1.pcap 2> /dump-eth1.err\n",
    }
    # the local copies are removed once sent
    assert list((tmp_path / "exp").iterdir()) == []
    assert mm.filter == ""

    mm.log.clear()
    component.stop()
    assert mm.log == [
        ("uuid=of-aa", "rm -f /dump-eth0.pcap /dump-eth0.pid /dump-eth0.err"),
        ("uuid=of-bb", "rm -f /dump-eth1.pcap /dump-eth1.pid /dump-eth1.err"),
    ]
    assert mm.filter == ""


def test_stop_kills_by_pid_file_and_logs_failure(monkeypatch, tmp_path, caplog_loguru):
    component, _, waited = make_component(
        MD,
        tmp_path,
        monkeypatch,
        exec_results={
            "bash -c 'kill": {"stdout": None, "stderr": "no such pid", "exitcode": 1}
        },
    )

    component.stop()  # carries on past the failure

    assert ("aa", "bash -c 'kill $(cat /dump-eth0.pid)'") in waited
    assert not any("pkill" in cmd for _, cmd in waited)
    assert "could not stop tcpdump in VM aa using /dump-eth0.pid" in caplog_loguru()


def test_no_inline_cc_command_has_a_bare_variable(monkeypatch, tmp_path):
    """minimega expands a bare $name in an inline cc command, to nothing."""

    component, mm, waited = make_component(MD, tmp_path, monkeypatch)
    component.start()
    component.stop()

    inline = [cmd for _, cmd in waited] + [cmd for _, cmd in mm.log]
    assert any("$(" in cmd for cmd in inline)  # the check sees the kill commands
    assert [c for c in inline if re.search(r"\$(?!\()[A-Za-z_@$]", c)] == []


def test_start_rejects_missing_interface(monkeypatch, tmp_path):
    component, mm, _ = make_component(
        MD,
        tmp_path,
        monkeypatch,
        exec_results={"ip link show": {"stdout": "", "stderr": "", "exitcode": 1}},
    )

    with pytest.raises(RuntimeError, match="interface eth0 does not exist in VM aa"):
        component.start()
    assert mm.log == []


def test_start_with_iface_any_skips_the_link_check(monkeypatch, tmp_path):
    md = {"vms": [{"hostname": "aa", "iface": "any", "filter": "tcp port 502"}]}
    component, mm, waited = make_component(
        md,
        tmp_path,
        monkeypatch,
        exec_results={"ip link show": {"stdout": "", "stderr": "", "exitcode": 1}},
    )

    component.start()

    assert not any(cmd.startswith("ip link") for _, cmd in waited)
    assert [cmd for _, cmd in mm.log if cmd.startswith("ip link")] == []
    assert (
        "-i any -U -w /dump-any.pcap 'tcp port 502'"
        in component.sent["tcpdump_aa_any.sh"]
    )


def test_start_stops_a_lingering_tcpdump(monkeypatch, tmp_path, caplog_loguru):
    component, _, waited = make_component(
        MD,
        tmp_path,
        monkeypatch,
        exec_results={"bash -c 'if [ -s": {"stdout": "killed", "exitcode": 0}},
    )

    component.start()

    assert "/dump-eth0.pid" in waited[2][1]
    assert "kill $(cat /dump-eth0.pid)" in waited[2][1]
    assert "left running in VM aa" in caplog_loguru()


def test_conversion_failure_and_timeout_are_logged_not_raised(
    monkeypatch, tmp_path, caplog_loguru
):
    md = {**MD, "convert_to_json": True, "convertTimeout": 7}
    component, _, _ = make_component(md, tmp_path, monkeypatch)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw["timeout"]))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        return subprocess.CompletedProcess(cmd, 2, stderr="bad capture\n")

    monkeypatch.setattr("subprocess.run", run)

    component.stop()

    assert [t for _, t in calls] == [7, 7]
    assert calls[0][0] == ["tshark", "-r", f"{tmp_path}/aa-eth0.pcap", "-T", "ek"]
    log = caplog_loguru()
    assert "timed out after 7.0s" in log
    assert "failed (tshark exit 2): bad capture" in log


def test_conversion_success(monkeypatch, tmp_path):
    component, _, _ = make_component(
        {**MD, "convert_to_json": True}, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "subprocess.run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0)
    )
    assert component._convert(str(tmp_path / "x.pcap"), str(tmp_path / "x.jsonl"))


@pytest.mark.parametrize(
    ("run", "message"),
    [
        ({"start": ["t"], "stop": []}, "not in the matching stop list"),
        ({"start": ["t"], "stop": ["c", "t"]}, "after the collector"),
        ({"loop": {"start": ["t"], "stop": ["c", "t"]}}, "after the collector"),
        ({"start": ["t"], "stop": ["t", "c"]}, None),
        ({"start": ["x"], "stop": []}, None),
    ],
)
def test_stage_list_warnings(monkeypatch, tmp_path, caplog_loguru, run, message):
    scorch = {"components": [{"name": "c", "type": "collector"}], "runs": [run]}
    component, _, _ = make_component(MD, tmp_path, monkeypatch, scorch=scorch)

    component.start()

    log = caplog_loguru()
    if message:
        assert message in log
    else:
        assert "stop list" not in log
        assert "collector" not in log
