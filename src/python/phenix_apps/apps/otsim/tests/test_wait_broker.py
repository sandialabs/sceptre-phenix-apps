"""Tests for the broker wait script ot-sim injects when there is no helics app."""

import subprocess

import pytest
from box import Box

from phenix_apps.apps.otsim.app import OTSim

pytestmark = pytest.mark.app_class(
    cls=OTSim,
    name="ot-sim",
    stage="pre-start",
    real_methods=["extract_node", "extract_nodes_type"],
)


@pytest.fixture
def wait_script(mock_app, tmp_path):
    def wait_script(address):
        mock_app.metadata = Box({"helics": {"broker": {"address": address}}})
        mock_app.app = Box(
            {
                "hosts": [
                    {
                        "hostname": "rtu-1",
                        "metadata": {
                            "type": "fd-server",
                            "dnp3": [{"type": "breaker", "name": "brkr-1"}],
                        },
                    }
                ]
            }
        )
        mock_app.experiment.spec.topology.nodes = [
            {
                "general": {"hostname": "rtu-1"},
                "network": {"interfaces": [{"name": "IF0", "address": "10.0.0.1"}]},
            }
        ]
        mock_app.extract_app.return_value = None
        mock_app.otsim_dir = tmp_path
        mock_app._OTSim__init_defaults()

        mock_app.pre_start()

        return tmp_path / "wait-broker-0.sh"

    return wait_script


@pytest.mark.parametrize(
    ("address", "probe"),
    [("10.0.0.250", "10.0.0.250/23404"), ("10.0.0.250:23500", "10.0.0.250/23500")],
)
def test_federate_waits_for_the_broker_port(wait_script, address, probe):
    script = wait_script(address)
    text = script.read_text()

    assert f'timeout 1 bash -c "exec 3<> /dev/tcp/{probe}"' in text
    assert "ping" not in text
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_invalid_broker_address_names_the_host(wait_script):
    with pytest.raises(ValueError, match="'rtu-1' has an invalid broker"):
        wait_script("10.0.0.250:http")
