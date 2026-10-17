import io
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.ssh.ssh import (
    MAX_USER_LENGTH,
    NO_TIMEOUT,
    SSH,
    SSHMetadata,
)
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"
BASE = {"ip": "10.0.0.1", "user": "u", "cmds": ["ls"]}


def readme_examples() -> list[dict]:
    return readme_components(README, "ssh")


def test_readme_has_examples():
    assert len(readme_examples()) == 3


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(SSHMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_readme_background_example_releases_the_session():
    (cmp,) = [c for c in readme_examples() if c["name"] == "recorder-start"]
    last = cmp["metadata"]["cmds"][-1]
    assert last.startswith("(")
    assert last.endswith("&)")
    assert "> /dev/null 2>&1 < /dev/null" in last


def test_defaults():
    config = parse_metadata(SSHMetadata, BASE, "s")

    assert str(config.ip) == "10.0.0.1"
    assert (config.port, config.password, config.files) == (22, None, [])


def test_values_are_stripped():
    config = parse_metadata(
        SSHMetadata,
        {
            **BASE,
            "user": " bob ",
            "password": " pw ",
            "cmds": [" ls "],
            "files": [" /a "],
        },
        "s",
    )
    assert (config.user, config.password) == ("bob", "pw")
    assert (config.cmds, config.files) == (["ls"], ["/a"])


def test_timeout_defaults():
    config = parse_metadata(SSHMetadata, BASE, "s")
    assert (config.connect_timeout, config.banner_timeout, config.login_timeout) == (
        10,
        0,
        0,
    )


@pytest.mark.parametrize(
    "cmd", ["echo ok # don't change this", "cat <<'EOF'\ndon't\nEOF"]
)
def test_scripts_are_not_syntax_checked(cmd):
    parse_metadata(SSHMetadata, {**BASE, "cmds": [cmd]}, "s")


@pytest.mark.parametrize(
    ("md", "expected"),
    [
        ({}, (10, NO_TIMEOUT, NO_TIMEOUT)),
        ({"connect_timeout": 0, "banner_timeout": 3, "login_timeout": 4}, (None, 3, 4)),
    ],
)
def test_connect_passes_timeouts(monkeypatch, md, expected):
    seen = {}

    class Client:
        def set_missing_host_key_policy(self, _):
            pass

        def connect(self, **kw):
            seen.update(kw)

    monkeypatch.setattr("paramiko.SSHClient", Client)
    component = SSH.__new__(SSH)
    component.config = parse_metadata(SSHMetadata, {**BASE, **md}, "s")

    component._connect()

    assert (seen["timeout"], seen["banner_timeout"], seen["auth_timeout"]) == expected


@pytest.mark.parametrize(
    ("md", "problem"),
    [
        ({"ip": "ssh.lab"}, "ip: value is not a valid IPv4 or IPv6 address"),
        ({"ip": "10.0.0.256"}, "ip: value is not a valid IPv4 or IPv6 address"),
        ({"user": ""}, "user: String should have at least 1 character"),
        ({"user": "   "}, "user: String should have at least 1 character"),
        (
            {"user": "u" * (MAX_USER_LENGTH + 1)},
            f"user: String should have at most {MAX_USER_LENGTH} characters",
        ),
        ({"password": ""}, "password: String should have at least 1 character"),
        ({"password": 1234}, "password: Input should be a valid string"),
        ({"port": 0}, "port: Input should be greater than or equal to 1"),
        ({"port": "22"}, "port: Input should be a valid integer"),
        ({"cmds": "ls"}, "cmds: Input should be a valid list"),
        ({"cmds": []}, "cmds: List should have at least 1 item"),
        ({"cmds": [""]}, "cmds.0: String should have at least 1 character"),
        ({"cmds": ["  "]}, "cmds.0: String should have at least 1 character"),
        ({"cmds": [5]}, "cmds.0: Input should be a valid string"),
        ({"files": "/tmp/x"}, "files: Input should be a valid list"),
        ({"files": None}, "files: Input should be a valid list"),
        ({"files": [""]}, "files.0: String should match pattern"),
        ({"files": ["/"]}, "files.0: Value error, path must name a file"),
        ({"files": ["/tmp/.."]}, "files.0: Value error, path must name a file"),
        ({"files": ["/tmp/a\0b"]}, "files.0: String should match pattern"),
        ({"files": ["/a b"]}, "files.0: String should match pattern"),
        ({"files": ["/a/x", "/b/x"]}, "more than one entry ends in 'x'"),
        (
            {"connect_timeout": -1},
            "connect_timeout: Input should be greater than or equal to 0",
        ),
        ({"login_timeout": "5"}, "login_timeout: Input should be a valid number"),
    ],
)
def test_bad_values_fail(md, problem):
    with pytest.raises(ValueError, match="1 problem") as exc:
        parse_metadata(SSHMetadata, {**BASE, **md}, "s")

    assert problem in str(exc.value)


def test_user_at_the_limit_is_valid():
    parse_metadata(SSHMetadata, {**BASE, "user": "u" * MAX_USER_LENGTH}, "s")


def test_ipv6_and_paths_are_valid():
    md = {**BASE, "ip": "fe80::1", "files": ["/var/log/app", "rel/dir/", "/a/c.log"]}
    assert str(parse_metadata(SSHMetadata, md, "s").ip) == "fe80::1"


def test_unknown_key_warns_with_hint():
    _, warnings = validate_metadata(SSHMetadata, {**BASE, "file": ["/x"]}, "s")

    assert len(warnings) == 1
    assert "file: unknown key, ignored" in warnings[0]
    assert "did you mean 'files'?" in warnings[0]


@pytest.mark.parametrize("missing", ["ip", "user", "cmds"])
def test_required_fields(missing):
    md = dict(BASE)
    del md[missing]
    with pytest.raises(ValueError, match=f"{missing}: Field required"):
        parse_metadata(SSHMetadata, md, "s")


class FakeChannel:
    def __init__(self, status):
        self.status = status

    def recv_exit_status(self):
        return self.status


class FakeStream(io.BytesIO):
    def __init__(self, data: bytes, status: int):
        super().__init__(data)
        self.channel = FakeChannel(status)


class FakeClient:
    def __init__(self, status):
        self.status = status

    def exec_command(self, command):
        return (
            None,
            FakeStream(b"out\n", self.status),
            FakeStream(b"err\n", self.status),
        )


@pytest.mark.parametrize("status", [0, 2])
def test_remote_command_records_its_exit_status(status):
    component = SSH.__new__(SSH)
    component.config = SSHMetadata(ip="10.0.0.1", user="u", cmds=["ls"])

    result = component._run_remote_command(FakeClient(status), "false")

    assert result == {
        "host": "10.0.0.1",
        "cmd": "false",
        "exit_status": status,
        "stdout": "out",
        "stderr": "err",
    }
