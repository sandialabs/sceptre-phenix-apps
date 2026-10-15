"""Tests for how field device servers pick their infrastructure."""

from box import Box

from phenix_apps.apps.otsim.device import FieldDeviceServer


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
