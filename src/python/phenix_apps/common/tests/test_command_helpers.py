"""
Tests for the shared command helpers: values spliced into raw minimega
commands must be single tokens, and run_command never goes through a shell.
"""

import importlib

import pytest

from phenix_apps.common import settings, utils
from phenix_apps.common.error import AppError


class TestValidateMmToken:
    @pytest.mark.parametrize("value", ["exp1", "node-2", "a.b_c"])
    def test_accepts(self, value):
        assert utils._validate_mm_token(value) == value

    @pytest.mark.parametrize(
        "value",
        ["", "two words", "new\nline", "tab\there", "quo'te", 'dou"ble'],
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

    @pytest.mark.parametrize("value", ["x' or 1", 'a"b', "a\nb", "a\rb"])
    def test_rejects_quotes_and_line_breaks(self, value):
        with pytest.raises(AppError):
            utils._validate_mm_filter(value)


def test_mm_capture_filename_allows_timestamps():
    from phenix_apps.apps.scorch.mm import mm

    assert mm._validate_filename("br0-2024-01-01T10:00:00Z+x.pcap")
    for bad in ["two words.pcap", "a.pcap\n"]:
        with pytest.raises(AppError):
            mm._validate_filename(bad)


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
        for bad in [None, "10.0.0.1; reboot", "host"]:
            with pytest.raises(AppError):
                utils.validate_ip(bad, "ip")
