from pathlib import Path
from unittest.mock import MagicMock

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.trafficgen.trafficgen import TrafficGen, TrafficgenMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"
SCRIPTS = {"trafficServer": "/s/server.py", "backgroundGen": "/s/bg.py"}


def readme_examples() -> list[dict]:
    return readme_components(README, "trafficgen")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(TrafficgenMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    md = {
        "scripts": {**SCRIPTS, "malwareGen": "/s/mw.py"},
        "targets": [{"backgroundClient": {}, "malwareClient": {}}],
    }
    (t,) = parse_metadata(TrafficgenMetadata, md, "t").targets

    assert (t.hostname, t.interface, t.duration) == ("traffic-server", "IF0", 5)
    assert t.backgroundClient is not None
    assert t.backgroundClient.model_dump() == {
        "hostname": "background-gen",
        "rate": 10000,
        "probability": 0.01,
    }
    assert t.malwareClient is not None
    assert t.malwareClient.model_dump() == {
        "hostname": "malware-gen",
        "rate": 20,
        "probability": 1.25,
    }


def test_clients_are_optional():
    (t,) = parse_metadata(
        TrafficgenMetadata,
        {"scripts": {"trafficServer": "/s/a.py"}, "targets": [{}]},
        "t",
    ).targets
    assert t.backgroundClient is None
    assert t.malwareClient is None


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({}, "scripts: Field required"),
        ({"scripts": SCRIPTS}, "targets: Field required"),
        ({"scripts": SCRIPTS, "targets": []}, "targets: List should have at least 1"),
        ({"scripts": {}, "targets": [{}]}, r"scripts\.trafficServer: Field required"),
        (
            {"scripts": {"trafficServer": "/a b;rm"}, "targets": [{}]},
            r"scripts\.trafficServer",
        ),
        ({"scripts": SCRIPTS, "targets": [{"hostname": "a;reboot"}]}, "hostname"),
        ({"scripts": SCRIPTS, "targets": [{"hostname": "a"}]}, "hostname"),
        ({"scripts": SCRIPTS, "targets": [{"interface": "x y"}]}, "interface"),
        ({"scripts": SCRIPTS, "targets": [{"duration": -1}]}, "duration"),
        ({"scripts": SCRIPTS, "targets": [{"duration": "5"}]}, "duration"),
        ({"scripts": SCRIPTS, "targets": [{"duration": 1.5}]}, "duration"),
        (
            {"scripts": SCRIPTS, "targets": [{"backgroundClient": {"rate": 0}}]},
            "rate",
        ),
        (
            {
                "scripts": SCRIPTS,
                "targets": [{"backgroundClient": {"probability": float("nan")}}],
            },
            "probability",
        ),
        (
            {
                "scripts": SCRIPTS,
                "targets": [{"backgroundClient": {"probability": float("inf")}}],
            },
            "probability",
        ),
        (
            {
                "scripts": SCRIPTS,
                "targets": [{"backgroundClient": {"probability": 100.1}}],
            },
            "probability",
        ),
        (
            {"scripts": SCRIPTS, "targets": [{"backgroundClient": {"rate": "x"}}]},
            "rate",
        ),
        (
            {"scripts": SCRIPTS, "targets": [{"malwareClient": {}}]},
            r"scripts\.malwareGen: required when a target has malwareClient",
        ),
        (
            {
                "scripts": {"trafficServer": "/s/a.py"},
                "targets": [{"backgroundClient": {}}],
            },
            r"scripts\.backgroundGen: required when a target has backgroundClient",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(TrafficgenMetadata, md, "t")


def test_unknown_key_only_warns():
    md = {"scripts": SCRIPTS, "targets": [{"bogus": 1}]}
    _, warnings = validate_metadata(TrafficgenMetadata, md, "t")

    assert len(warnings) == 1
    assert warnings[0].startswith(
        "targets.0.bogus: unknown key, ignored. Fix: remove it (known: hostname, "
    )


ALL_SCRIPTS = {**SCRIPTS, "malwareGen": "/s/mw.py"}


def run_stage(monkeypatch, stage, targets):
    """Run one stage with minimega mocked; return the recorded call list."""

    calls = MagicMock()
    comp = object.__new__(TrafficGen)
    comp.name = "t"
    comp.config = parse_metadata(
        TrafficgenMetadata, {"scripts": ALL_SCRIPTS, "targets": targets}, "t"
    )
    monkeypatch.setattr(comp, "mm_init", lambda: calls.mm)
    monkeypatch.setattr(comp, "extract_node_ip", lambda host, iface: "10.0.0.1")
    monkeypatch.setattr("phenix_apps.common.utils.mm_send", calls.send)
    monkeypatch.setattr("time.sleep", calls.sleep)
    getattr(comp, stage)()
    return calls


def filters_and_cmds(calls):
    return [c.args[0] for c in calls.mm.method_calls]


MALWARE_ONLY = [{"malwareClient": {"hostname": "mw1"}}]


def test_malware_only_target_still_drives_the_server(monkeypatch):
    configure = run_stage(monkeypatch, "configure", MALWARE_ONLY)
    assert [c.args[1:] for c in configure.send.call_args_list] == [
        ("traffic-server", "/s/server.py", "server.py"),
        ("mw1", "/s/mw.py", "mw.py"),
    ]

    start = run_stage(monkeypatch, "start", MALWARE_ONLY)
    assert filters_and_cmds(start) == [
        "name=traffic-server",
        "python3 /server.py",
        "name=mw1",
        "python3 /mw.py --ip 10.0.0.1 --rate 20 --duration 5 --probability 1.25",
    ]
    start.sleep.assert_called_once_with(10)

    stop = run_stage(monkeypatch, "stop", MALWARE_ONLY)
    assert filters_and_cmds(stop) == [
        "name=traffic-server",
        "pkill -f server.py",
        "name=mw1",
        "pkill -f mw.py",
    ]

    cleanup = run_stage(monkeypatch, "cleanup", MALWARE_ONLY)
    assert filters_and_cmds(cleanup) == [
        "name=traffic-server",
        "rm /server.py",
        "name=mw1",
        "rm /mw.py",
    ]


def test_both_clients_get_their_own_commands(monkeypatch):
    start = run_stage(
        monkeypatch,
        "start",
        [{"duration": 30, "backgroundClient": {}, "malwareClient": {}}],
    )
    assert filters_and_cmds(start) == [
        "name=traffic-server",
        "python3 /server.py",
        "name=background-gen",
        "python3 /bg.py --ip 10.0.0.1 --rate 10000 --duration 30 --probability 0.01",
        "name=malware-gen",
        "python3 /mw.py --ip 10.0.0.1 --rate 20 --duration 30 --probability 1.25",
    ]
    start.sleep.assert_called_once_with(35)


def test_server_only_target_runs_just_the_server(monkeypatch):
    stop = run_stage(monkeypatch, "stop", [{}])
    assert filters_and_cmds(stop) == ["name=traffic-server", "pkill -f server.py"]
