"""Tests for the DNP3 scan rates pre-start gives FEPs and field device clients."""

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
def run(mock_app, tmp_path):
    def run(helics):
        mock_app.metadata = Box({"helics": {"broker": {"address": "10.0.0.250"}}})
        mock_app.metadata.helics.update(helics)
        mock_app.app = Box(
            {
                "hosts": [
                    {
                        "hostname": "rtu-1",
                        "metadata": {
                            "type": "fd-server",
                            "dnp3": [{"type": "breaker", "name": "brkr-1"}],
                        },
                    },
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

        def scan_rate(hostname):
            root = ET.parse(mock_app.otsim_dir / f"{hostname}.xml").getroot()
            return root.findtext("dnp3[@mode='client']/master/scan-rate")

        return scan_rate("fep-1"), scan_rate("scada")

    return run


def test_client_uses_configured_scan_rate(run):
    assert run({"scan-rate": 2}) == ("2", "2")


def test_client_omits_default_scan_rate(run):
    """FEPs default to 5 with helics set; clients keep the ot-sim default."""

    assert run({}) == ("5", None)
