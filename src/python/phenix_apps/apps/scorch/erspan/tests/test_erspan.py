from pathlib import Path
from unittest.mock import Mock

import pytest
from box import Box
from loguru import logger

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.erspan.erspan import ERSPAN, ERSPANMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"

BASE = {"local_bridge": "phenix", "local_ip": "192.168.1.2", "remote_ip": "192.168.1.3"}
REMOTE = {"ssh_ip": "192.168.1.3", "user": "u"}


def readme_examples() -> list[dict]:
    return readme_components(README, "erspan")


def test_readme_has_examples():
    assert len(readme_examples()) == 3


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(ERSPANMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults():
    config = parse_metadata(ERSPANMetadata, {**BASE, "remote_config": REMOTE}, "e")

    assert config.local_interface == "erspan1"
    assert config.session_key == 100
    assert config.excluded_vlans == []
    assert config.remote_config.remote_interface == "erspan1"
    assert config.remote_config.port == 22


def test_unknown_key_in_remote_config_warns_with_hint():
    md = {**BASE, "remote_config": {**REMOTE, "remote_brige": "b"}}
    _, warnings = validate_metadata(ERSPANMetadata, md, "e")

    assert len(warnings) == 1
    assert "remote_config.remote_brige: unknown key" in warnings[0]
    assert "did you mean 'remote_bridge'?" in warnings[0]


def test_empty_remote_config_means_local_only():
    config = parse_metadata(ERSPANMetadata, {**BASE, "remote_config": {}}, "e")
    assert config.remote_config is None


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"local_bridge": None}, "local_bridge"),
        ({"local_interface": "a-very-long-name-1"}, "local_interface"),
        ({"local_bridge": "--help"}, "local_bridge"),
        ({"local_ip": "phenix-host"}, "local_ip: value is not a valid IP"),
        ({"local_ip": "phenix-host", "remote_config": REMOTE}, "local_ip: value"),
        ({"remote_ip": "receiver"}, "remote_ip: value is not a valid IP"),
        ({"session_key": -1}, "session_key"),
        ({"session_key": "200"}, "session_key: Input should be a valid integer"),
        ({"excluded_vlans": 5}, "excluded_vlans: Input should be a valid list"),
        ({"local_ip": "fe80::1%$(id)"}, "local_ip: Value error, scoped IPv6"),
        ({"remote_ip": "fe80::1%eth0"}, "remote_ip: Value error, scoped IPv6"),
        (
            {"remote_config": {**REMOTE, "ssh_ip": "fe80::1%$(id)"}},
            r"remote_config\.ssh_ip: Value error, scoped IPv6",
        ),
        (
            {"remote_config": {**REMOTE, "ssh_timeout": 0}},
            r"remote_config\.ssh_timeout",
        ),
        ({"excluded_vlans": [""]}, "excluded_vlans.0: String should have at least 1"),
        ({"remote_config": {"user": "u"}}, r"remote_config\.ssh_ip"),
        ({"remote_config": {"ssh_ip": "192.168.1.3"}}, r"remote_config\.user"),
        (
            {"remote_config": {**REMOTE, "ssh_ip": "receiver.lab"}},
            r"remote_config\.ssh_ip: value is not a valid IP",
        ),
        (
            {"remote_config": {**REMOTE, "user": "u" * 33}},
            r"remote_config\.user: String should have at most 32",
        ),
        (
            {"remote_config": {**REMOTE, "password": 1234}},
            r"remote_config\.password: Input should be a valid string",
        ),
        (
            {"remote_config": {**REMOTE, "remote_interface": "a-very-long-name-1"}},
            r"remote_config\.remote_interface",
        ),
        (
            {"remote_config": {**REMOTE, "remote_bridge": "a b"}},
            r"remote_config\.remote_bridge",
        ),
        ({"remote_config": {**REMOTE, "port": 0}}, r"remote_config\.port"),
    ],
)
def test_unsafe_or_broken_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(ERSPANMetadata, {**BASE, **md}, "e")


def test_single_vlan_name_and_empty_remote_interface_still_work():
    md = {
        **BASE,
        "excluded_vlans": "mgmt",
        "remote_config": {**REMOTE, "remote_interface": ""},
    }
    config = parse_metadata(ERSPANMetadata, md, "e")

    assert config.excluded_vlans == ["mgmt"]
    assert config.remote_config.remote_interface == "erspan1"


def test_ssh_timeout_defaults_to_none_and_accepts_seconds():
    config = parse_metadata(ERSPANMetadata, {**BASE, "remote_config": REMOTE}, "e")
    assert config.remote_config.ssh_timeout is None

    rc = {**REMOTE, "ssh_timeout": 2.5}
    config = parse_metadata(ERSPANMetadata, {**BASE, "remote_config": rc}, "e")
    assert config.remote_config.ssh_timeout == 2.5


def erspan(vlans: dict, excluded: list[str]) -> ERSPAN:
    component = ERSPAN.__new__(ERSPAN)
    component.experiment = Box({"status": {"vlans": vlans}})
    component.config = ERSPANMetadata.model_validate(
        {**BASE, "excluded_vlans": excluded}
    )
    return component


def test_mirrored_vlans_skip_the_excluded_ones():
    vlans = {"MGMT": 200, "ot": 101, "it": 100}
    assert erspan(vlans, ["mgmt"])._get_mirrored_vlans() == [100, 101]


def test_excluding_every_vlan_is_an_error():
    with pytest.raises(ValueError, match="no VLANs left to mirror"):
        erspan({"mgmt": 200}, ["mgmt"])._get_mirrored_vlans()


def test_mirror_command_selects_the_vlans():
    cmd = erspan({}, [])._configure_mirror([100, 101], "phenix", "m0", "erspan1")
    assert "select_vlan=100,101 output-port=@p" in cmd


def test_mirror_is_named_after_the_interface_and_added_not_replaced():
    component = erspan({}, [])
    cmd = component._configure_mirror(
        [100], "phenix", component._mirror_name, "erspan1"
    )

    assert component._mirror_name == "scorch-erspan1"
    assert "create Mirror name=scorch-erspan1 " in cmd
    assert cmd.endswith("-- add Bridge phenix mirrors @m")


def test_other_mirrors_on_the_bridge_are_warned_about():
    component = erspan({}, [])
    warnings = []
    handler = logger.add(warnings.append, level="WARNING")
    try:
        component._run_mm = lambda cmd: {"stdout": ["[]"]}
        component._warn_about_other_mirrors()
        assert not warnings

        component._run_mm = lambda cmd: {"stdout": ["[1b2c, 3d4e]"]}
        component._warn_about_other_mirrors()
        assert "already has mirrors [1b2c, 3d4e]" in str(warnings[0])
    finally:
        logger.remove(handler)


class FakeSSH:
    """paramiko.SSHClient stand-in: the exit status per command, in order."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.ran = []
        self.timeouts = []

    def set_missing_host_key_policy(self, _):
        pass

    def connect(self, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))

    def close(self):
        pass

    def exec_command(self, command, timeout=None):
        self.ran.append(command)
        self.timeouts.append(timeout)
        status = self.statuses.pop(0)
        out = Mock()
        out.read.return_value = b""
        out.channel.recv_exit_status.return_value = status
        err = Mock()
        err.read.return_value = f"boom{status}".encode()
        return None, out, err


def remote(monkeypatch, statuses, timeout=None) -> tuple[ERSPAN, FakeSSH]:
    ssh = FakeSSH(statuses)
    monkeypatch.setattr("paramiko.SSHClient", lambda: ssh)
    rc = {**REMOTE, "ssh_timeout": timeout} if timeout else REMOTE
    component = ERSPAN.__new__(ERSPAN)
    component.erspan_metadata = []
    component.config = ERSPANMetadata.model_validate({**BASE, "remote_config": rc})
    return component, ssh


def test_remote_commands_stop_at_the_first_failure_by_default(monkeypatch):
    component, ssh = remote(monkeypatch, [0, 3, 0])
    with pytest.raises(RuntimeError, match="exit code 3"):
        component._run_remote_commands(["a", "b", "c"], "config_remote")
    assert ssh.ran == ["a", "b"]


def test_remote_cleanup_runs_everything_and_reports_every_failure(monkeypatch):
    component, ssh = remote(monkeypatch, [1, 0, 2])
    with pytest.raises(RuntimeError) as err:
        component._run_remote_commands(
            ["a", "b", "c"], "cleanup_remote", keep_going=True
        )
    assert ssh.ran == ["a", "b", "c"]
    assert "exit code 1" in str(err.value)
    assert "exit code 2" in str(err.value)


def test_ssh_timeout_reaches_paramiko(monkeypatch):
    component, ssh = remote(monkeypatch, [0], timeout=7)
    component._run_remote_commands(["a"], "config_remote")
    assert ssh.timeouts == [7, 7]
