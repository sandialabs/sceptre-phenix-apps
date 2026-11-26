"""Tests for how field device servers pick and expand their infrastructure."""

from pathlib import Path

import lxml.etree as ET
import pytest
from box import Box

from phenix_apps.apps.otsim.device import FieldDeviceServer
from phenix_apps.apps.otsim.infrastructure import Infrastructure
from phenix_apps.apps.otsim.protocols.dnp3 import DNP3
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.testing.readme import readme_yaml

README = Path(__file__).parents[1] / "README.md"

VECTOR_MAPPINGS = {
    "three-phase": {
        "bus": {
            "voltage_magnitude": {
                "type": "analog-read",
                "phases": 3,
                "modbus": {"scaling": 2},
                "dnp3": {"class": 2},
            },
            "status": "binary-read",
        },
    },
}


def server(metadata, *args):
    device = FieldDeviceServer(Box({"metadata": metadata}), *args)
    device.process({})
    return {reg.tag for reg in device.registers["dnp3"]}


def test_server_uses_default_infrastructure():
    tags = server(
        {"dnp3": [{"type": "bus", "name": "bus-1"}]}, "power-3-phase-distribution"
    )

    assert "bus-1.Va-mag" in tags
    assert "bus-1.voltage" not in tags


def test_host_infrastructure_overrides_default():
    md = {
        "infrastructure": "power-distribution",
        "dnp3": [{"type": "bus", "name": "bus-1"}],
    }

    assert server(md, "power-3-phase-distribution") == {"bus-1.voltage"}


def vector_server(mappings=VECTOR_MAPPINGS):
    devices = [{"type": "bus", "name": "OpenDSS/bus-1"}]
    device = FieldDeviceServer(
        Box({"metadata": {"dnp3": devices, "modbus": devices}}), "three-phase"
    )
    device.process(mappings)
    return device


@pytest.mark.parametrize(
    ("protocol", "md"), [("dnp3", {"class": 2}), ("modbus", {"scaling": 2})]
)
def test_vector_variable_gets_a_register_per_phase(protocol, md):
    regs = vector_server().registers[protocol]

    assert [(reg.tag, reg.variable, reg.md) for reg in regs] == [
        ("bus-1.voltage_magnitude_0", "voltage_magnitude_0", md),
        ("bus-1.voltage_magnitude_1", "voltage_magnitude_1", md),
        ("bus-1.voltage_magnitude_2", "voltage_magnitude_2", md),
        ("bus-1.status", "status", {}),
    ]


def test_scalar_variable_keeps_its_protocol_settings():
    voltage = {"type": "analog-read", "dnp3": {"class": 1, "sgvar": 5}}
    voltage["modbus"] = {"scaling": 3}
    regs = vector_server({"three-phase": {"bus": {"voltage": voltage}}}).registers

    assert [(reg.tag, reg.md) for reg in regs["dnp3"]] == [
        ("bus-1.voltage", {"class": 1, "sgvar": 5})
    ]
    assert [(reg.tag, reg.md) for reg in regs["modbus"]] == [
        ("bus-1.voltage", {"scaling": 3})
    ]


def test_vector_registers_render_for_each_protocol():
    device = vector_server()

    dnp3 = DNP3()
    dnp3.init_xml_root("server", Box({"metadata": {}, "topology": topology()}))
    dnp3.init_outstation_xml()
    dnp3.registers_to_xml(device.registers["dnp3"])
    analogs = dnp3.outstn.findall("input[@type='analog']")

    assert [(p.findtext("address"), p.findtext("tag")) for p in analogs] == [
        ("0", "bus-1.voltage_magnitude_0"),
        ("1", "bus-1.voltage_magnitude_1"),
        ("2", "bus-1.voltage_magnitude_2"),
    ]

    modbus = Modbus()
    modbus.init_xml_root("server", Box({"metadata": {}, "topology": topology()}))
    modbus.registers_to_xml(device.registers["modbus"])
    inputs = modbus.root.findall("register[@type='input']")

    assert [(r.findtext("address"), r.findtext("tag")) for r in inputs] == [
        ("30001", "bus-1.voltage_magnitude_0"),
        ("30002", "bus-1.voltage_magnitude_1"),
        ("30003", "bus-1.voltage_magnitude_2"),
    ]
    assert {r.findtext("scaling") for r in inputs} == {"-2"}


def topology():
    return {"network": {"interfaces": [{"name": "IF0", "address": "10.0.0.1"}]}}


def io_module(mappings, infra):
    doc = ET.Element("io")
    devices = {"OpenDSS/bus-1": {"type": "bus", "endpoint": "OpenDSS/updates"}}
    Infrastructure(mappings).io_module_xml(doc, infra, devices)
    return {
        sub.findtext("key"): (sub.findtext("tag"), sub.findtext("type"))
        for sub in doc.findall("subscription")
    }


def test_vector_variable_subscribes_as_a_vector():
    assert io_module(VECTOR_MAPPINGS, "three-phase") == {
        "OpenDSS/bus-1.voltage_magnitude": ("bus-1.voltage_magnitude", "vector"),
        "OpenDSS/bus-1.status": ("bus-1.status", "boolean"),
    }


def test_scalar_variable_subscribes_as_a_double():
    subs = io_module({}, "power-distribution")

    assert subs == {"OpenDSS/bus-1.voltage": ("bus-1.voltage", "double")}


@pytest.mark.parametrize(
    "var_type",
    [
        {"type": "analog-read", "phases": 0},
        {"type": "analog-read", "phases": "3"},
        {"type": "analog-read", "phases": True},
        {"type": "analog-read-write", "phases": 3},
        {"type": "binary-read", "phases": 3},
    ],
)
def test_invalid_phases_are_rejected(var_type):
    mappings = {"three-phase": {"bus": {"voltage": var_type}}}

    with pytest.raises(ValueError, match="'voltage' sets phases"):
        vector_server(mappings)

    with pytest.raises(ValueError, match="'voltage' sets phases"):
        io_module(mappings, "three-phase")


def test_readme_vector_example_expands():
    (example,) = readme_yaml(README, "Three phase variables")
    md = example["spec"]["scenario"]["apps"][0]["metadata"]
    host = example["spec"]["scenario"]["apps"][0]["hosts"][0]["metadata"]
    device = FieldDeviceServer(Box({"metadata": host}), md["infrastructure"])
    device.process(md["infrastructures"])

    assert [reg.tag for reg in device.registers["dnp3"]] == [
        "bus-1.voltage_magnitude_0",
        "bus-1.voltage_magnitude_1",
        "bus-1.voltage_magnitude_2",
    ]
