import shlex
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.art import art
from phenix_apps.apps.scorch.art.art import ARTMetadata, AtomicRedTeam
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"
VM = {"hostname": "aa"}


def readme_examples() -> list[dict]:
    return readme_components(README, "art")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(ARTMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    config = parse_metadata(
        ARTMetadata, {"technique": "T1006", "testIndex": 0, "vms": [VM]}, "a"
    )

    assert config.testName is None
    assert config.abortOnError is False
    assert config.goartPath is None
    assert config.env == {}
    assert config.validator is None
    assert config.vms[0].env == {}
    assert config.vms[0].inputs == {}


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"testIndex": 0, "vms": [VM]}, "technique: Field required"),
        ({"technique": "", "testIndex": 0, "vms": [VM]}, "technique"),
        ({"technique": "T1006", "vms": [VM]}, "set testName or testIndex"),
        ({"technique": "T1006; reboot", "testIndex": 0, "vms": [VM]}, "technique"),
        ({"technique": "T1006", "testIndex": -1, "vms": [VM]}, "testIndex"),
        ({"technique": "T1006", "testName": "", "vms": [VM]}, "testName"),
        ({"technique": "T1006", "testName": "a;b", "vms": [VM]}, "testName"),
        ({"technique": "T1006", "testIndex": 0}, "vms: Field required"),
        ({"technique": "T1006", "testIndex": 0, "vms": []}, "at least 1 item"),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [{"hostname": "a"}]},
            "hostname",
        ),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [VM], "abortOnError": "x"},
            "abortOnError",
        ),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [VM], "goartPath": "a b"},
            "goartPath",
        ),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [VM], "env": {"A B": "1"}},
            "env",
        ),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [VM], "env": {"A": "x;y"}},
            "env",
        ),
        (
            {"technique": "T1006", "testIndex": 0, "vms": [VM], "env": {"A": "x\ny"}},
            "env",
        ),
        (
            {
                "technique": "T1006",
                "testIndex": 0,
                "vms": [{"hostname": "aa", "inputs": {"k=v": "1"}}],
            },
            "inputs",
        ),
        (
            {
                "technique": "T1006",
                "testIndex": 0,
                "vms": [{"hostname": "aa", "inputs": {"k": "$(id)"}}],
            },
            "inputs",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(ARTMetadata, md, "a")


def test_unknown_vm_key_only_warns():
    md = {"technique": "T1006", "testIndex": 0, "vms": [{**VM, "bogus": 1}]}
    _, warnings = validate_metadata(ARTMetadata, md, "a")

    assert len(warnings) == 1
    assert warnings[0].startswith("vms.0.bogus: unknown key, ignored.")
    assert "(known: " in warnings[0]


def component(**md):
    comp = object.__new__(AtomicRedTeam)
    comp.config = ARTMetadata.model_validate(
        {"technique": "T1006", "testIndex": 0, "vms": [VM], **md}
    )
    return comp


@pytest.mark.parametrize(
    ("os_type", "path"),
    [("linux", "/phenix/art/goart"), ("windows", "C:/phenix/art/goart.exe")],
)
def test_goart_path_defaults_per_os(os_type, path):
    assert component()._goart_path(os_type) == path


@pytest.mark.parametrize("os_type", ["linux", "windows"])
def test_goart_path_override_wins(os_type):
    assert component(goartPath="/opt/goart")._goart_path(os_type) == "/opt/goart"


def run_start(tmp_path, monkeypatch, **md):
    """Run start() against a recording mock; return the goart command sent."""
    sent = []
    comp = component(**md)
    comp.name = "art"
    comp.base_dir = tmp_path
    comp.mm_init = lambda: None
    comp.extract_node_os_type = lambda _hostname: "linux"
    comp._check_binary = lambda *a: None
    monkeypatch.setattr(art.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art.utils, "mm_exec_wait", lambda _mm, _h, c: sent.append(c))
    monkeypatch.setattr(
        art.utils, "mm_recv", lambda _mm, _h, _src, dst: dst.write_text("{}")
    )
    comp.start()
    return shlex.split(sent[0])


def test_start_spaced_test_name_is_quoted(tmp_path, monkeypatch):
    argv = run_start(
        tmp_path, monkeypatch, testIndex=None, testName="Dump LSASS memory"
    )

    assert argv[argv.index("-n") + 1] == "Dump LSASS memory"


def test_start_builds_goart_command(tmp_path, monkeypatch):
    argv = run_start(
        tmp_path,
        monkeypatch,
        testName="ignored",
        testIndex=3,
        goartPath="/opt/goart",
        env={"A": "1"},
        vms=[{**VM, "env": {"B": "2"}, "inputs": {"c": "3"}}],
    )

    assert argv[0] == "/opt/goart"
    assert argv[argv.index("-t") + 1] == "T1006"
    assert argv[argv.index("-i") + 1] == "3"
    assert "-n" not in argv
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--env"] == ["A=1", "B=2"]
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--input"] == ["c=3"]
