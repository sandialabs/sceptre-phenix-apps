"""Tests for the configs pre-start gives field device servers, FEPs and clients."""

import lxml.etree as ET
import pytest
from box import Box

from phenix_apps.apps.otsim.app import OTSim

pytestmark = pytest.mark.app_class(
    cls=OTSim,
    name="ot-sim",
    stage="pre-start",
    real_methods=["extract_node", "extract_nodes_type"],
)


def topo(hostname, address):
    return {
        "general": {"hostname": hostname},
        "network": {"interfaces": [{"name": "IF0", "address": address}]},
    }


@pytest.fixture
def pre_start(mock_app, tmp_path):
    """Run pre-start with app `helics` metadata and the rtu-1 `helics` block."""

    def pre_start(helics, host_helics=None):
        mock_app.metadata = Box({"helics": {"broker": {"address": "10.0.0.250"}}})
        mock_app.metadata.helics.update(helics)
        rtu = {"type": "fd-server", "dnp3": [{"type": "breaker", "name": "brkr-1"}]}
        if host_helics is not None:
            rtu["helics"] = host_helics
        mock_app.app = Box(
            {
                "hosts": [
                    {"hostname": "rtu-1", "metadata": rtu},
                    {
                        "hostname": "fep-1",
                        "metadata": {"type": "fep", "connected_rtus": ["rtu-1"]},
                    },
                    {
                        "hostname": "scada",
                        "metadata": {"type": "fd-client", "connected_rtus": ["fep-1"]},
                    },
                ]
            }
        )
        mock_app.experiment.spec.topology.nodes = [
            topo("rtu-1", "10.0.0.1"),
            topo("fep-1", "10.0.0.2"),
            topo("scada", "10.0.0.3"),
        ]
        mock_app.otsim_dir = tmp_path / "configs"
        mock_app.otsim_dir.mkdir()
        mock_app._OTSim__init_defaults()

        mock_app.pre_start()

        return lambda hostname: ET.parse(mock_app.otsim_dir / f"{hostname}.xml")

    return pre_start


@pytest.fixture
def run(pre_start):
    def run(helics):
        config = pre_start(helics)

        def scan_rate(hostname):
            return config(hostname).findtext("dnp3[@mode='client']/master/scan-rate")

        return scan_rate("fep-1"), scan_rate("scada")

    return run


def test_client_uses_configured_scan_rate(run):
    assert run({"scan-rate": 2}) == ("2", "2")


def test_client_omits_default_scan_rate(run):
    """FEPs default to 5 with helics set; clients keep the ot-sim default."""

    assert run({}) == ("5", None)


def io_settings(pre_start, helics, host_helics=None):
    io = pre_start(helics, host_helics)("rtu-1").find("io")
    return io.findtext("step-time"), io.findtext("full-status-steps")


def test_io_module_leaves_step_settings_to_otsim_by_default(pre_start):
    assert io_settings(pre_start, {}) == (None, None)


def test_io_module_uses_app_step_settings(pre_start):
    helics = {"step-time": 0.5, "full-status-steps": 30}

    assert io_settings(pre_start, helics) == ("0.5", "30")


def test_host_step_settings_override_the_app(pre_start):
    helics = {"step-time": 2, "full-status-steps": 30}

    assert io_settings(pre_start, helics, {"step-time": 5}) == ("5", "30")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("step-time", 0),
        ("step-time", "1s"),
        ("step-time", True),
        ("full-status-steps", 1.5),
        ("full-status-steps", -1),
    ],
)
def test_invalid_step_settings_are_rejected(pre_start, key, value):
    with pytest.raises(ValueError, match=f"'rtu-1' has an invalid helics.{key}"):
        pre_start({key: value})
