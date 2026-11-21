"""Tests for the DNP3 master config FEPs and field device clients generate."""

import pytest
from box import Box

from phenix_apps.apps.otsim.config import Config
from phenix_apps.apps.otsim.device import (
    DEFAULT_DOWNSTREAM,
    DOWNSTREAM_PROTOCOLS,
    FEP,
    FieldDeviceClient,
    FieldDeviceServer,
)


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


def chain(fep_md):
    """A Modbus field device behind a FEP, and a client behind the FEP."""

    rtu = FieldDeviceServer(
        node("rtu-1", {"modbus": [{"type": "breaker", "name": "brkr-1"}]}, "10.0.0.1")
    )
    rtu.process({})
    known = {"rtu-1": rtu}
    fep = FEP(node("fep-1", {"connected_rtus": ["rtu-1"], **fep_md}, "10.0.0.2"))
    fep.process(known)
    known["fep-1"] = fep

    client = FieldDeviceClient(node("scada", {"connected_rtus": ["fep-1"]}, "10.0.0.3"))
    config = Config()
    config.init_xml_root()
    client.process(known)
    client.configure(config, known)
    return config.root


def test_client_behind_fep_polls_its_default_dnp3_outstation():
    """The FEP serves DNP3 downstream by default, whatever it polls upstream."""

    root = chain({})

    assert root.findtext("dnp3[@mode='client']/endpoint") == "10.0.0.2:20000"
    assert root.find("dnp3[@mode='client']/master/input") is not None
    assert root.find("modbus[@mode='client']") is None


def test_client_behind_fep_follows_its_downstream_protocols():
    root = chain({"downstream": "modbus"})

    assert root.findtext("modbus[@mode='client']/endpoint") == "10.0.0.2:502"
    assert root.find("dnp3[@mode='client']") is None


def test_fep_behind_fep_polls_what_the_upstream_fep_serves():
    rtu = FieldDeviceServer(
        node("rtu-1", {"modbus": [{"type": "breaker", "name": "brkr-1"}]}, "10.0.0.1")
    )
    rtu.process({})
    known = {"rtu-1": rtu}
    known["fep-1"] = FEP(node("fep-1", {"connected_rtus": ["rtu-1"]}, "10.0.0.2"))
    fep2 = FEP(
        node("fep-2", {"upstream": ["fep-1"], "downstream": "modbus"}, "10.0.0.4")
    )
    config = Config()
    config.init_xml_root()
    fep2.process(known)
    fep2.configure(config, known)

    assert config.root.findtext("dnp3[@mode='client']/endpoint") == "10.0.0.2:20000"
    assert config.root.find("modbus[@mode='client']") is None
    assert config.root.findtext("modbus[@mode='server']/endpoint") == "10.0.0.4:502"


@pytest.mark.parametrize(
    ("downstream", "expected"),
    [
        ([], list(DEFAULT_DOWNSTREAM)),
        (["modbus", "dnp3"], list(DOWNSTREAM_PROTOCOLS)),
        (["modbus", "iec104"], ["modbus"]),
    ],
)
def test_fep_downstream_picks_from_the_shared_protocol_list(downstream, expected):
    fep = FEP(node("fep-1", {"downstream": downstream}, "10.0.0.2"))
    assert fep.downstream() == expected
