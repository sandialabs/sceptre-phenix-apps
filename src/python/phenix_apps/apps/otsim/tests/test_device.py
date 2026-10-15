"""Tests for the DNP3 master config FEPs and field device clients generate."""

import pytest
from box import Box

from phenix_apps.apps.otsim.config import Config
from phenix_apps.apps.otsim.device import FEP, FieldDeviceClient, FieldDeviceServer


def node(hostname, metadata, address):
    return Box(
        {
            "general": {"hostname": hostname},
            "metadata": metadata,
            "topology": {
                "network": {"interfaces": [{"name": "IF0", "address": address}]}
            },
        }
    )


@pytest.fixture
def devices():
    rtu = FieldDeviceServer(
        node("rtu-1", {"dnp3": [{"type": "breaker", "name": "brkr-1"}]}, "10.0.0.1")
    )
    rtu.process({})
    return {"rtu-1": rtu}


def configure(device, devices):
    config = Config()
    config.init_xml_root()
    device.process(devices)
    device.configure(config, devices)
    return config.root.find("dnp3[@mode='client']/master")


@pytest.mark.parametrize("cls", [FEP, FieldDeviceClient])
def test_master_omits_scan_rate_when_unset(cls, devices):
    """Without a scan rate the element is left out so ot-sim applies its own
    default (issue #72)."""

    device = cls(node("fep-1", {"connected_rtus": ["rtu-1"]}, "10.0.0.2"))
    master = configure(device, devices)

    assert master is not None
    assert master.find("scan-rate") is None
    assert master.findall("input")


@pytest.mark.parametrize("cls", [FEP, FieldDeviceClient])
def test_master_uses_configured_scan_rate(cls, devices):
    device = cls(
        node("fep-1", {"connected_rtus": ["rtu-1"]}, "10.0.0.2"), {"scan-rate": 10}
    )
    master = configure(device, devices)

    assert master.findtext("scan-rate") == "10"
