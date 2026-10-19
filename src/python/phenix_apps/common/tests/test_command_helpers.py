"""
Tests for the shared command helpers: values spliced into raw minimega
commands must be single tokens, and run_command never goes through a shell.
"""

import importlib
import subprocess
from pathlib import Path

import pytest

from phenix_apps.common import settings, utils
from phenix_apps.common.error import AppError


class TestValidateMmToken:
    @pytest.mark.parametrize("value", ["exp1", "node-2", "a.b_c"])
    def test_accepts(self, value):
        assert utils._validate_mm_token(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "two words",
            "new\nline",
            "tab\there",
            "quo'te",
            'dou"ble',
            "#",
            "pipe#rest",
            "back\\slash",
        ],
    )
    def test_rejects(self, value):
        with pytest.raises(AppError):
            utils._validate_mm_token(value)


class TestRunCommand:
    def test_string_form_is_shlex_split_not_shell(self):
        # A shell would expand the glob and the semicolon; argv exec must not.
        out = utils.run_command("echo 'a; touch /tmp/pwned' *")
        assert out.strip() == "a; touch /tmp/pwned *"

    def test_list_form_passthrough(self):
        assert utils.run_command(["echo", "hi"]).strip() == "hi"


@pytest.mark.parametrize(
    ("value", "expected"), [(None, True), ("1", True), ("0", False)]
)
def test_scorch_host_validators_on_unless_zero(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("PHENIX_SCORCH_HOST_VALIDATORS", raising=False)
    else:
        monkeypatch.setenv("PHENIX_SCORCH_HOST_VALIDATORS", value)
    try:
        assert importlib.reload(settings).SCORCH_HOST_VALIDATORS is expected
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


class TestValidateMmFilter:
    def test_accepts_spaces(self):
        assert utils._validate_mm_filter("tcp port 80") == "tcp port 80"

    @pytest.mark.parametrize(
        "value", ["x' or 1", 'a"b', "a\nb", "a\rb", "a\\nb", "a\\", "a#b"]
    )
    def test_rejects_quotes_backslashes_comments_and_line_breaks(self, value):
        with pytest.raises(AppError):
            utils._validate_mm_filter(value)


def test_mm_capture_filename_allows_timestamps():
    from phenix_apps.apps.scorch.mm import mm

    assert mm._validate_filename("br0-2024-01-01T10:00:00Z+x.pcap")
    for bad in ["two words.pcap", "a.pcap\n"]:
        with pytest.raises(AppError):
            mm._validate_filename(bad)


class FakeMM:
    """Records every minimega call as (method, *args)."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


def make_mm_component(tmp_path, metadata):
    from box import Box

    from phenix_apps.apps.scorch.mm import mm

    component = object.__new__(mm.MM)
    component.metadata = Box(metadata)
    component.base_dir = tmp_path
    component.root_dir = tmp_path
    component.mm_init = lambda: component.fake
    component.fake = FakeMM()
    return component


class TestMmComponentQuoting:
    def test_bridge_capture_filter_reaches_minimega_as_one_quoted_argument(
        self, tmp_path
    ):
        component = make_mm_component(
            tmp_path,
            {
                "start": [
                    {
                        "type": "start_capture",
                        "capture": {"bridge": "phenix", "filter": "tcp port 80"},
                    }
                ]
            },
        )
        component._MM__run("start")

        assert ("capture_pcap_filter", "'tcp port 80'") in component.fake.calls

    def test_vm_capture_filter_reaches_minimega_as_one_quoted_argument(self, tmp_path):
        component = make_mm_component(
            tmp_path,
            {
                "start": [],
                "vms": [
                    {
                        "hostname": "vm1",
                        "start": [
                            {
                                "type": "start_capture",
                                "capture": {"interface": 0, "filter": "not port 22"},
                            }
                        ],
                    }
                ],
            },
        )
        component._MM__run("start")

        assert ("capture_pcap_filter", "'not port 22'") in component.fake.calls

    @pytest.mark.parametrize("filter_", ["a\\b", "a#b", "it's"])
    def test_filter_minimega_would_misread_fails_before_any_command(
        self, tmp_path, filter_
    ):
        component = make_mm_component(
            tmp_path,
            {
                "start": [
                    {
                        "type": "start_capture",
                        "capture": {"bridge": "phenix", "filter": filter_},
                    }
                ]
            },
        )
        with pytest.raises(AppError):
            component._MM__run("start")

        assert component.fake.calls == []

    @pytest.mark.parametrize("hostname", ["vm1 vm2", "vm1#", "vm'1"])
    def test_vm_name_must_be_one_token(self, tmp_path, hostname):
        component = make_mm_component(
            tmp_path,
            {"vms": [{"hostname": hostname, "start": [{"type": "start"}]}]},
        )
        with pytest.raises(AppError):
            component._MM__run("start")

        assert component.fake.calls == []

    @pytest.mark.parametrize("hostname", ["vm1", "vm[1-3]", "a,b"])
    def test_vm_name_may_be_a_minimega_target(self, tmp_path, hostname):
        component = make_mm_component(
            tmp_path,
            {"vms": [{"hostname": hostname, "start": [{"type": "start"}]}]},
        )
        component._MM__run("start")

        assert component.fake.calls == [("vm_start", hostname)]


def test_mm_snaplen_must_be_a_non_negative_integer():
    from phenix_apps.apps.scorch.mm import mm

    assert mm._validate_snaplen(" 96 ") == 96
    for bad in ["96 -w /x", -1]:
        with pytest.raises(AppError):
            mm._validate_snaplen(bad)


def test_pcap_tshark_split_keeps_the_display_filter_one_argument():
    from pathlib import Path

    from phenix_apps.apps.scorch.pcap.pcap import PCAP

    cmd = PCAP._tshark_split(Path("/r/a b.pcap"), Path("/r/out.pcap"), "not (x > 0)")
    assert cmd[cmd.index("-r") + 1] == "/r/a b.pcap"
    assert cmd[-2:] == ["-Y", "not (x > 0)"]


class TestMetadataValidators:
    def test_ovs_name(self):
        assert utils.validate_ovs_name("br-0", "bridge") == "br-0"
        for bad in [None, "", "two words", "abcdefghijklmnop", 7, "br0\n"]:
            with pytest.raises(AppError):
                utils.validate_ovs_name(bad, "bridge")

    def test_ip(self):
        assert utils.validate_ip("10.0.0.1", "ip") == "10.0.0.1"
        assert utils.validate_ip("fe80::1", "ip") == "fe80::1"
        for bad in [
            None,
            "10.0.0.1; reboot",
            "host",
            "fe80::1%eth0",
            "fe80::1%$(id)",
            "fe80::1%eth0; id #",
        ]:
            with pytest.raises(AppError):
                utils.validate_ip(bad, "ip")


class TestMmConvertPcap:
    def test_failure_removes_partial_output(self, monkeypatch, tmp_path):
        from phenix_apps.apps.scorch.mm import mm

        def fail(cmd, stdout, **_):
            stdout.write("partial")
            raise subprocess.CalledProcessError(2, cmd, stderr="cut short\n")

        monkeypatch.setattr(mm.subprocess, "run", fail)
        out = tmp_path / "a.pcap.jsonl"
        with pytest.raises(AppError, match="exit 2"):
            mm._convert_pcap(str(tmp_path / "a.pcap"), str(out))
        assert not out.exists()

    def test_missing_tshark_removes_output(self, monkeypatch, tmp_path):
        from phenix_apps.apps.scorch.mm import mm

        def missing(*_, **__):
            raise FileNotFoundError("tshark")

        monkeypatch.setattr(mm.subprocess, "run", missing)
        out = tmp_path / "a.pcap.jsonl"
        with pytest.raises(AppError):
            mm._convert_pcap(str(tmp_path / "a.pcap"), str(out))
        assert not out.exists()


class TestKafkaIsListener:
    @pytest.fixture
    def is_listener(self, monkeypatch):
        from phenix_apps.apps.scorch.kafka import kafka_component

        comp = object.__new__(kafka_component.Kafka)
        comp.exp_name = "exp1"
        comp.component_id = "abc123"

        def check(*argv: bytes) -> bool:
            def read(_):
                if not argv:
                    raise FileNotFoundError
                return b"\0".join(argv)

            monkeypatch.setattr(Path, "read_bytes", read)
            return comp._is_listener(42)

        return check

    @pytest.fixture
    def listener(self):
        from phenix_apps.apps.scorch.kafka import kafka_component

        return str(kafka_component.LISTENER).encode()

    def test_matches_own_listener(self, is_listener, listener):
        assert is_listener(b"python3", listener, b"True", b"exp1", b"305", b"abc123")

    def test_rejects_editor_other_experiment_and_gone(self, is_listener, listener):
        assert not is_listener(b"vim", listener)
        assert not is_listener(b"python3", listener, b"True", b"exp2", b"abc123")
        # sibling kafka component in the same experiment
        assert not is_listener(b"python3", listener, b"True", b"exp1", b"def456")
        assert not is_listener(b"python3", listener + b".bak", b"exp1", b"abc123")
        assert not is_listener()
