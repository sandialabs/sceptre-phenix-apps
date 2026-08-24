"""Tests for the configure-stage handlers.

These assert on the injections a handler adds, since configure() only declares
what file goes where -- the files themselves are produced in pre-start.
"""

import pytest

from phenix_apps.apps.sceptre.app import Sceptre
from phenix_apps.apps.sceptre.configure import ConfigureStage
from phenix_apps.apps.sceptre.tests.conftest import iface, node
from phenix_apps.common import error

pytestmark = pytest.mark.app_class(cls=Sceptre, name="sceptre")


def injects(app):
    """Every inject the handler produced, as {dst: src}."""
    return {
        call.kwargs["inject"]["dst"]: call.kwargs["inject"]["src"]
        for call in app.add_inject.call_args_list
    }


class TestFindOverride:
    def test_returns_none_when_no_override_exists(self, sceptre_app, tmp_path):
        sceptre_app.asset_dir = str(tmp_path / "assets")

        assert Sceptre.find_override(sceptre_app, "opc-1_opc.xml") is None

    def test_returns_override_src_when_present(self, sceptre_app, tmp_path):
        override = tmp_path / "assets" / "injects" / "override" / "opc-1_opc.xml"
        override.parent.mkdir(parents=True)
        override.write_text("<opc/>")
        sceptre_app.asset_dir = str(tmp_path / "assets")

        assert Sceptre.find_override(sceptre_app, "opc-1_opc.xml") == {
            "src": str(override)
        }

    def test_unmatched_override_files_are_reported(self, sceptre_app, tmp_path, caplog):
        override_dir = tmp_path / "assets" / "injects" / "override"
        override_dir.mkdir(parents=True)
        (override_dir / "opc-1_opc.xml").write_text("<opc/>")
        (override_dir / "opc-9_opc.xml").write_text("<opc/>")  # typo'd hostname
        sceptre_app.asset_dir = str(tmp_path / "assets")

        Sceptre.find_override(sceptre_app, "opc-1_opc.xml")
        Sceptre._warn_unused_overrides(sceptre_app)

        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("opc-9_opc.xml" in w for w in warnings)
        assert not any("opc-1_opc.xml" in w for w in warnings)


class TestInject:
    """The one place an injection dict is built."""

    def last(self, app):
        return app.add_inject.call_args.kwargs["inject"]

    def test_no_override_named_means_no_lookup(self, sceptre_app):
        sceptre_app.inject("opc-1", "/gen/opc.xml", "C:/opc.xml", "OPC config")

        sceptre_app.find_override.assert_not_called()
        assert self.last(sceptre_app) == {
            "src": "/gen/opc.xml",
            "dst": "C:/opc.xml",
            "description": "OPC config",
        }

    def test_override_is_looked_up_under_the_hostname(self, sceptre_app):
        sceptre_app.find_override.return_value = {"src": "/assets/opc-1_opc.xml"}

        sceptre_app.inject(
            "opc-1", "/gen/opc.xml", "C:/opc.xml", "OPC config", override="opc.xml"
        )

        sceptre_app.find_override.assert_called_once_with("opc-1_opc.xml")
        assert self.last(sceptre_app)["src"] == "/assets/opc-1_opc.xml"

    def test_permissions_are_omitted_unless_given(self, sceptre_app):
        sceptre_app.inject("rtu-1", "/gen/a.sh", "/etc/a.sh", "startup")
        assert "permissions" not in self.last(sceptre_app)

        sceptre_app.inject(
            "rtu-1", "/gen/b.sh", "/etc/b.sh", "startup", permissions="0744"
        )
        assert self.last(sceptre_app)["permissions"] == "0744"


class TestOpc:
    def test_injects_generated_config_by_default(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [node("opc-1")]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).opcs()

        assert injects(sceptre_app)[
            "Users/wwuser/Documents/Configs/Inject/opc.xml"
        ] == (f"{sceptre_app.sceptre_dir}/opc-1/opc.xml")

    def test_override_wins_over_generated_config(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [node("opc-1")]
        sceptre_app.find_override.side_effect = lambda name: (
            {"src": f"/assets/{name}"} if "opc.xml" in name else None
        )

        ConfigureStage(sceptre_app).opcs()

        assert injects(sceptre_app)[
            "Users/wwuser/Documents/Configs/Inject/opc.xml"
        ] == ("/assets/opc-1_opc.xml")


class TestProviders:
    def test_no_providers_is_an_error(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = []

        with pytest.raises(error.AppError, match="No SCEPTRE providers"):
            ConfigureStage(sceptre_app).providers()

    def test_provider_without_metadata_is_skipped(self, sceptre_app):
        bare = node("provider-1")
        del bare["metadata"]
        sceptre_app.extract_nodes_type.return_value = [bare]

        ConfigureStage(sceptre_app).providers()

        sceptre_app.add_inject.assert_not_called()

    @pytest.mark.parametrize(
        ("simulator", "expected_config_dst"),
        [
            ("PowerWorld", "sceptre/config.ini"),
            ("PowerWorldHelics", "sceptre/config.ini"),
            ("PowerWorldDynamics", "/etc/sceptre/config.ini"),
            ("PyPower", "/etc/sceptre/config.ini"),
            ("GenericPython", "/etc/sceptre/config.ini"),
            ("", "/etc/sceptre/config.ini"),  # unknown -> default branch
        ],
    )
    def test_simulator_selects_config_destination(
        self, sceptre_app, simulator, expected_config_dst
    ):
        metadata = {
            "simulator": simulator,
            "case": "/assets/case.PWB",
            "oneline": "/assets/oneline.pwd",
            "simulation_file": "/assets/sim.py",
        }
        sceptre_app.extract_nodes_type.return_value = [
            node("provider-1", metadata, interfaces=[iface("IF0", "10.0.0.1")])
        ]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).providers()

        assert expected_config_dst in injects(sceptre_app)

    def test_powerworld_injects_case_and_oneline(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [
            node(
                "provider-1",
                {
                    "simulator": "PowerWorld",
                    "case": "/assets/case.PWB",
                    "oneline": "/assets/oneline.pwd",
                },
            )
        ]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).providers()

        result = injects(sceptre_app)
        assert result["sceptre/case.PWB"] == "/assets/case.PWB"
        assert result["sceptre/oneline.pwd"] == "/assets/oneline.pwd"

    def test_simulink_ground_truth_is_optional(self, sceptre_app):
        metadata = {
            "simulator": "simulink",
            "solver": "/assets/solver",
            "publish_points": "/assets/points.txt",
        }
        sceptre_app.extract_nodes_type.return_value = [node("provider-1", metadata)]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).providers()

        assert "/etc/sceptre/simulinkgt" not in injects(sceptre_app)


class TestScadaServers:
    def test_supplied_project_injects_the_mep_file(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [
            node("scada-1", {"project": "/assets/myscada.mep"})
        ]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).scada_servers()

        assert injects(sceptre_app)[
            "Users/wwuser/Documents/Configs/Inject/myscada.mep"
        ] == ("/assets/myscada.mep")

    def test_no_project_injects_the_autogenerated_directory(self, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [node("scada-1", {"some": "md"})]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).scada_servers()

        assert injects(sceptre_app)["Users/wwuser/Documents/"] == (
            f"{sceptre_app.sceptre_dir}/scada-1/autoproject"
        )


class TestElk:
    def test_more_than_one_elk_box_is_an_error(self, sceptre_app):
        sceptre_app.extract_nodes_label.return_value = []
        sceptre_app.extract_nodes_type.return_value = [node("elk-1"), node("elk-2")]

        with pytest.raises(error.AppError, match="multiple ELK boxes"):
            ConfigureStage(sceptre_app).elk()

    def test_beat_startup_script_is_written_for_linux_only(self, sceptre_app):
        sceptre_app.extract_nodes_label.return_value = [
            node("elk-linux", os_type="linux"),
            node("elk-windows", os_type="windows"),
        ]
        sceptre_app.extract_nodes_type.return_value = []
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).elk()

        assert (sceptre_app.startup_dir / "elk-linux-elk-start.sh").exists()
        assert not (sceptre_app.startup_dir / "elk-windows-elk-start.sh").exists()


class TestHelics:
    def test_broker_startup_script_counts_the_federates(self, sceptre_app):
        sceptre_app.extract_nodes_label.side_effect = [
            [node("fed-1"), node("fed-2"), node("fed-3")],  # helics-federate
            [node("broker-1", {}, os_type="linux")],  # helics-broker
        ]
        sceptre_app.find_override.return_value = None

        ConfigureStage(sceptre_app).helics()

        script = open(f"{sceptre_app.startup_dir}/broker-1-helics.sh").read()
        assert "-f 3" in script
