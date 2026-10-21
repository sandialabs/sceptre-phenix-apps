from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.disruption.disruption import (
    Disruption,
    DisruptionMetadata,
    check_physical_results,
)
from phenix_apps.common.logger import logger
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "disruption")


def readme_example(name: str) -> dict:
    (cmp,) = [c for c in readme_examples() if c["name"] == name]
    return cmp["metadata"]


def dos_metadata(**overrides) -> dict:
    md = {
        "current_disruption": "dos",
        "run_duration": 300.0,
        "dos": {
            "attack_duration": 120.0,
            "start_delay": 60.0,
            "attacker": {
                "hostname": "attacker",
                "script_path": "/root/dos.py",
                "results_path": "/root/out.json",
            },
            "targets": [{"hostname": "load5"}],
        },
    }
    md.update(overrides)
    return md


def test_readme_has_one_example_per_disruption():
    names = {cmp["metadata"]["current_disruption"] for cmp in readme_examples()}
    assert names == {"baseline", "dos", "physical", "cyber_physical"}


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid(cmp):
    parse_metadata(DisruptionMetadata, cmp["metadata"], cmp["name"])


def test_defaults():
    config = parse_metadata(DisruptionMetadata, dos_metadata(), "d")

    assert config.dos is not None
    assert config.dos.wrapup == 60.0
    assert config.dos.wait_margin == 5.0
    assert config.dos.attacker.interface == "eth0"
    assert config.dos.targets[0].interface == "eth0"


@pytest.mark.parametrize("disruption", ["baseline", "physical"])
def test_unused_but_invalid_dos_block_fails(disruption):
    md = readme_example("physical-scenario") | {
        "current_disruption": disruption,
        "dos": {"attack_duration": 1, "attacker": {"hostname": "bad name"}},
    }
    with pytest.raises(ValueError, match=r"dos\.attacker\.hostname"):
        parse_metadata(DisruptionMetadata, md, "d")


def test_unused_valid_block_is_kept():
    md = readme_example("cyber-physical") | {"current_disruption": "dos"}
    assert parse_metadata(DisruptionMetadata, md, "d").physical is not None


def test_unknown_keys_are_kept():
    config = parse_metadata(DisruptionMetadata, dos_metadata(note="x"), "d")
    assert config.model_extra == {"note": "x"}


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"current_disruption": "dos", "run_duration": 300}, "needs a dos block"),
        (
            {"current_disruption": "physical", "run_duration": 300},
            "needs a physical block",
        ),
        (dos_metadata(run_duration=100.0), "leaves no time to attack"),
        (
            readme_example("cyber-physical") | {"run_duration": 100.0},
            "leaves no time to attack",
        ),
        (dos_metadata(run_duration="inf"), "run_duration"),
        ({"current_disruption": "baseline", "run_duration": 0}, "run_duration"),
        ({}, "current_disruption: Field required"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(DisruptionMetadata, md, "d")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hostname", "attacker; reboot"),
        ("interface", "eth0 up"),
        ("script_path", "/root/dos.py --evil"),
        ("results_path", "/out.json&whoami"),
        ("results_path", "/*"),
        ("interface", "a" * 16),
        ("hostname", "a"),
    ],
)
def test_command_tokens_reject_whitespace(field, value):
    md = dos_metadata()
    md["dos"]["attacker"][field] = value

    with pytest.raises(ValueError, match=rf"dos\.attacker\.{field}"):
        parse_metadata(DisruptionMetadata, md, "d")


def test_physical_timeout_margin_default():
    config = parse_metadata(
        DisruptionMetadata, readme_example("physical-scenario"), "d"
    )
    assert config.physical is not None
    assert config.physical.timeout_margin == 15.0


def test_physical_start_delay_must_fit_run_duration():
    md = readme_example("physical-scenario") | {"run_duration": 60.0}

    with pytest.raises(ValueError, match=r"physical\.start_delay"):
        parse_metadata(DisruptionMetadata, md, "d")


@pytest.mark.parametrize(
    ("run_duration", "wrapup", "expected"),
    [
        (300.0, 60.0, 120.0),
        (200.0, 60.0, 79.0),
        (150.0, 10.0, 79.0),
        (150.0, 40.0, 49.0),
    ],
    # fits; cut to 200 - 61 - 60; wrapup moves the cut
)
def test_dos_run_for_fits_the_budget(run_duration, wrapup, expected):
    md = dos_metadata()
    md["dos"]["wrapup"] = wrapup
    config = parse_metadata(DisruptionMetadata, md, "d")
    assert config.dos is not None
    assert config.dos.run_for(run_duration) == expected


def test_physical_results_check():
    ok = {"scenario_duration": 30.0, "stages": {"a": {"successful": True}}}
    check_physical_results(ok)

    with pytest.raises(RuntimeError, match="did not run"):
        check_physical_results({"scenario_duration": 0.5, "stages": {}})

    failed = {
        "scenario_duration": 30.0,
        "stages": {
            "a": {"name": "trip", "successful": False, "status": "timeout"},
            "b": {"name": "open", "successful": False, "status": "refused"},
            "c": {"name": "ok", "successful": True},
        },
    }
    with pytest.raises(RuntimeError) as err:
        check_physical_results(failed)
    assert "2 disruption stage(s) failed" in str(err.value)
    assert "'trip': timeout" in str(err.value)
    assert "'open': refused" in str(err.value)


def test_unknown_nested_key_only_warns():
    md = dos_metadata()
    md["dos"]["attacker"]["iface"] = "eth1"
    config, warnings = validate_metadata(DisruptionMetadata, md, "d")

    assert config.dos is not None
    assert config.dos.attacker.interface == "eth0"
    assert warnings == [
        "dos.attacker.iface: unknown key, ignored. Fix: remove it "
        "(did you mean 'interface'?)"
    ]


def test_readme_examples_have_no_warnings():
    for cmp in readme_examples():
        assert validate_metadata(DisruptionMetadata, cmp["metadata"], "d")[1] == []


@pytest.mark.parametrize("field", ["results_path", "log_path"])
def test_physical_paths_reject_shell_characters(field):
    md = readme_example("physical-scenario")
    md["physical"][field] = "/out.json&whoami"

    with pytest.raises(ValueError, match=rf"physical\.{field}"):
        parse_metadata(DisruptionMetadata, md, "d")


def test_physical_windows_path_is_valid():
    md = readme_example("physical-scenario")
    md["physical"]["results_path"] = "C:/scorch/results.json"
    parse_metadata(DisruptionMetadata, md, "d")


def test_permutation_must_not_be_negative():
    with pytest.raises(ValueError, match="permutation"):
        parse_metadata(DisruptionMetadata, dos_metadata(permutation=-1), "d")


@pytest.mark.parametrize(
    ("overrides", "run_duration"),
    [({"start_delay": 0.0, "timeout_margin": 0.0}, 300.0), ({"start_delay": 0.0}, 1.0)],
)
def test_physical_timeout_must_be_positive(overrides, run_duration):
    md = readme_example("physical-scenario") | {"run_duration": run_duration}
    md["physical"] = md["physical"] | overrides

    with pytest.raises(ValueError, match="timeout is not positive"):
        parse_metadata(DisruptionMetadata, md, "d")


def test_physical_timeout_is_cut_to_run_duration():
    md = readme_example("physical-scenario") | {"run_duration": 70.0}
    config = parse_metadata(DisruptionMetadata, md, "d")
    assert config.physical is not None
    assert config.physical.timeout(70.0) == 69.0
    assert config.physical.timeout(300.0) == 75.0


def warnings_for(md: dict) -> list[str]:
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        parse_metadata(DisruptionMetadata, md, "d")
    finally:
        logger.remove(sink)
    return messages


def test_short_dos_attack_warns():
    md = dos_metadata()
    md["dos"]["attack_duration"] = 3.0
    (message,) = warnings_for(md)
    assert "only 3 seconds" in message

    # cut short by run_duration rather than by attack_duration
    (message,) = warnings_for(dos_metadata(run_duration=125.0))
    assert "only 4 seconds" in message

    assert warnings_for(dos_metadata()) == []


def stub_disruption(md: dict) -> Disruption:
    disruption = Disruption.__new__(Disruption)
    disruption.config = parse_metadata(DisruptionMetadata, md, "d")

    def node_ip(name: str, iface: str | int | None = None) -> str:
        return f"10.0.0.{len(name)}"

    disruption.extract_node_ip = node_ip  # type: ignore[method-assign]
    return disruption


def test_dos_command_includes_args():
    md = dos_metadata()
    assert "--target-ips 10.0.0.5 " in stub_disruption(md)._build_dos_cmd(60, 120)
    assert " --evil " not in stub_disruption(md)._build_dos_cmd(60, 120)

    md["dos"]["attacker"]["args"] = "--rate 10"
    cmd = stub_disruption(md)._build_dos_cmd(60, 120)
    assert cmd.startswith("/root/dos.py --rate 10 --wait-for 60 --run-for 120 ")


def test_attacker_os_picks_interface_command():
    md = dos_metadata()
    assert (
        stub_disruption(md)._attacker_iface_cmd("eth1", up=False)
        == "ip link set eth1 down"
    )

    md["dos"]["attacker"]["os_type"] = "windows"
    assert (
        stub_disruption(md)._attacker_iface_cmd("Eth1", up=True)
        == "netsh interface set interface name=Eth1 admin=enabled"
    )


def test_attacker_os_must_be_known():
    md = dos_metadata()
    md["dos"]["attacker"]["os_type"] = "plan9"
    with pytest.raises(ValueError, match=r"dos\.attacker\.os_type"):
        parse_metadata(DisruptionMetadata, md, "d")
