"""Tests for the stage accounting logged by app.py.

A successful run used to print nothing at all, so "did it even see my host?"
had no answer short of diffing the output tree. These assert the two lines that
answer it: the inventory, and the per-step counts.
"""

import pytest
from box import Box

from phenix_apps.apps.sceptre.app import Sceptre
from phenix_apps.apps.sceptre.tests.conftest import host

pytestmark = pytest.mark.app_class(cls=Sceptre, name="sceptre")


def log_lines(caplog):
    return [record.message for record in caplog.records]


class TestInventory:
    def test_lists_every_device_type_with_a_count(self, scenario, caplog):
        app = scenario()

        app._log_inventory("configure")

        line = next(
            m for m in log_lines(caplog) if f"{len(app.extract_all_nodes())} hosts" in m
        )
        for device_type in ("provider", "fd-server", "historian"):
            assert f"{device_type}={len(app.extract_nodes_type(device_type))}" in line
        federates = app.extract_nodes_label("helics-federate")
        assert f"helics-federate={len(federates)}" in line

    def test_a_missing_host_shows_up_as_a_smaller_count(self, scenario, caplog):
        """The whole point: you spot the omission by the number being wrong."""

        app = scenario(
            lambda e: e.spec.scenario.apps[0].__setitem__(
                "hosts",
                [h for h in e.spec.scenario.apps[0].hosts if h.hostname != "rtu-3"],
            )
        )

        app._log_inventory("configure")

        assert "fd-server=2" in next(m for m in log_lines(caplog) if "hosts --" in m)

    def test_absent_types_are_omitted_rather_than_shown_as_zero(self, scenario, caplog):
        """The fixture has every device type, so one has to be taken away."""

        app = scenario(
            lambda e: e.spec.scenario.apps[0].__setitem__(
                "hosts",
                [h for h in e.spec.scenario.apps[0].hosts if h.hostname != "fep-1"],
            )
        )

        app._log_inventory("configure")

        assert "fep=" not in next(m for m in log_lines(caplog) if "hosts --" in m)

    def test_untyped_hosts_are_named_at_debug(self, scenario, caplog):
        app = scenario()

        with caplog.at_level("DEBUG"):
            app._log_inventory("configure")

        assert any("fed-helics" in m for m in log_lines(caplog))


class TestStepAccounting:
    def test_reports_what_each_step_produced(self, caplog):
        counter = iter([0, 3, 3, 10])

        Sceptre._run_steps(
            None,
            (("first", lambda: None), ("second", lambda: None)),
            lambda: next(counter),
            "injection",
        )

        assert "  first                  +3 injections" in log_lines(caplog)
        assert "  second                 +7 injections" in log_lines(caplog)

    def test_singular_unit_for_one(self, caplog):
        counter = iter([0, 1])

        Sceptre._run_steps(
            None, (("only", lambda: None),), lambda: next(counter), "file"
        )

        assert "  only                   +1 file" in log_lines(caplog)

    def test_a_step_that_produced_nothing_drops_to_debug(self, caplog):
        """Idle steps stay out of the way at the default level."""

        Sceptre._run_steps(None, (("idle", lambda: None),), lambda: 0, "injection")

        record = next(r for r in caplog.records if "idle" in r.message)
        assert record.levelname == "DEBUG"
        assert "nothing to do" in record.message

    def test_steps_that_produced_something_are_info(self, caplog):
        counter = iter([0, 2])

        Sceptre._run_steps(
            None, (("busy", lambda: None),), lambda: next(counter), "injection"
        )

        record = next(r for r in caplog.records if "busy" in r.message)
        assert record.levelname == "INFO"


class TestCounters:
    def test_injection_count_sums_across_the_topology(self, sceptre_app):
        """Across nodes, not just the first, and a node may have none."""

        sceptre_app.experiment = Box(
            {
                "spec": {
                    "topology": {
                        "nodes": [
                            {"injections": [{"dst": "a"}, {"dst": "b"}]},
                            {"injections": [{"dst": "c"}]},
                            {},
                        ]
                    }
                }
            }
        )

        assert Sceptre._injection_count(sceptre_app) == 3

    def test_generated_file_count_tracks_the_experiment_dir(self, scenario, tmp_path):
        app = scenario()
        assert app._generated_file_count() == 0

        (tmp_path / "exp" / "startup").mkdir(parents=True, exist_ok=True)
        (tmp_path / "exp" / "startup" / "x.sh").write_text("")

        assert app._generated_file_count() == 1


def test_each_stage_logs_a_total(scenario, caplog):
    """One run of both stages: each ends with what it produced."""

    app = scenario()

    app.configure()
    total = app._injection_count()
    assert f"sceptre configure: {total} injections added" in log_lines(caplog)

    app.pre_start()
    assert any(
        m.startswith("sceptre pre-start: ") and "files generated under" in m
        for m in log_lines(caplog)
    )


def test_a_host_with_the_wrong_type_produces_no_injections_for_it(scenario, caplog):
    """A typo'd metadata.type is silent in the output but obvious in the log."""

    app = scenario(lambda e: host(e, "hmi-1").metadata.__setitem__("type", "hmiii"))

    app.configure()

    inventory = next(m for m in log_lines(caplog) if "hosts --" in m)
    assert "hmi=1" in inventory
