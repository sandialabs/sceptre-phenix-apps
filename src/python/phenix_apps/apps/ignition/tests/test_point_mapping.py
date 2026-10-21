"""Semantic tags built from ot-sim outstation metadata."""

import json

import pytest
from box import Box

from phenix_apps.apps.ignition.app import (
    HISTORY_PROVIDER_NAME,
    TAG_SYNC_NAME,
    Ignition,
    RtuDeviceConfig,
    device_tag_folder,
    history_properties,
    opc_item_path,
)
from phenix_apps.apps.otsim.points import OutstationPoint, Outstations

pytestmark = pytest.mark.app_class(cls=Ignition, name="ignition")

OTSIM_APP = Box(
    {
        "name": "ot-sim",
        "metadata": {},
        "hosts": [
            {"hostname": "rtu-1", "metadata": {"type": "fep", "upstream": ["ied-1"]}},
            {
                "hostname": "ied-1",
                "metadata": {
                    "type": "fd-server",
                    "dnp3": {
                        "interface": "eth1:20001",
                        "devices": [
                            {"name": "opendss/cap1", "type": "capacitor"},
                            {"name": "671692", "type": "breaker"},
                        ],
                    },
                },
            },
            {"hostname": "hmi", "metadata": {"type": "fd-client"}},
        ],
    }
)
TOPOLOGY = {
    "rtu-1": Box(
        {"network": {"interfaces": [{"name": "eth0", "address": "10.0.0.2"}]}}
    ),
    "ied-1": Box(
        {
            "network": {
                "interfaces": [
                    {"name": "eth0", "address": "10.0.0.3"},
                    {"name": "eth1", "address": "10.0.1.3"},
                ]
            }
        }
    ),
    "hmi": Box({"network": {"interfaces": [{"name": "eth0", "address": "10.0.0.4"}]}}),
}


def point(kind, index, device, variable, device_type="capacitor"):
    return OutstationPoint(
        kind=kind,
        index=index,
        tag=f"{device}.{variable}",
        device=device,
        device_type=device_type,
        variable=variable,
        register_type="analog-read",
        protocol="dnp3",
    )


@pytest.fixture
def otsim(mock_app):
    mock_app.extract_app.return_value = OTSIM_APP
    mock_app.extract_node.side_effect = TOPOLOGY.get
    return mock_app


def leaves(folder, prefix=""):
    for tag in folder["tags"]:
        path = f"{prefix}{tag['name']}"
        if tag["tagType"] == "Folder":
            yield from leaves(tag, path + "/")
        else:
            yield path, tag


# --- Resolution ---------------------------------------------------------------


def test_otsim_outstation_points_and_endpoint_are_used(otsim):
    (device,) = otsim._resolve_devices([RtuDeviceConfig(hostname="ied-1")])
    assert (device["ip"], device["port"]) == ("10.0.1.3", 20001)
    assert [(p.kind, p.index, p.device, p.variable) for p in device["points"]][:2] == [
        ("ai", 0, "cap1", "voltage"),
        ("ai", 1, "cap1", "current"),
    ]
    otsim.extract_node_ip.assert_not_called()


def test_explicit_interface_and_port_override_otsim(otsim):
    otsim.extract_node_ip.return_value = "10.0.0.3"
    (device,) = otsim._resolve_devices(
        [RtuDeviceConfig(hostname="ied-1", interface="eth0", port=20100)]
    )
    assert (device["ip"], device["port"]) == ("10.0.0.3", 20100)
    otsim.extract_node_ip.assert_called_once_with("ied-1", "eth0")


def test_fep_points_are_the_upstream_registers(otsim):
    (device,) = otsim._resolve_devices([RtuDeviceConfig(hostname="rtu-1")])
    assert (device["ip"], device["port"]) == ("10.0.0.2", 20000)
    assert [p.device for p in device["points"]] == ["cap1"] * 5 + ["671692"] * 6


def test_unknown_rtu_falls_back_to_discovery(otsim, mocker):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    otsim.extract_node_ip.return_value = "10.9.9.9"
    (device,) = otsim._resolve_devices([RtuDeviceConfig(hostname="other-rtu")])
    assert device["points"] is None
    assert device["ip"] == "10.9.9.9"
    assert "discovered on the gateway" in log.info.call_args.args[0]


def test_points_discover_skips_otsim(otsim):
    otsim.extract_node_ip.return_value = "10.0.0.3"
    (device,) = otsim._resolve_devices(
        [RtuDeviceConfig(hostname="ied-1", points="discover")]
    )
    assert device["points"] is None
    assert (device["ip"], device["port"]) == ("10.0.0.3", 20000)


def test_points_otsim_requires_an_otsim_host(otsim):
    with pytest.raises(ValueError, match="'other-rtu' has points: otsim"):
        otsim._resolve_devices([RtuDeviceConfig(hostname="other-rtu", points="otsim")])


def test_otsim_host_that_is_not_an_outstation_is_an_error(otsim):
    with pytest.raises(ValueError, match="'hmi' is type 'fd-client'"):
        otsim._resolve_devices([RtuDeviceConfig(hostname="hmi")])


def test_without_an_otsim_app_every_rtu_is_discovered(mock_app):
    mock_app.extract_app.return_value = None
    mock_app.extract_node_ip.return_value = "10.9.9.9"
    (device,) = mock_app._resolve_devices([RtuDeviceConfig(hostname="rtu-1")])
    assert device["points"] is None


def test_points_mode_is_validated():
    with pytest.raises(ValueError, match="points"):
        RtuDeviceConfig(hostname="rtu-1", points="guess")


# --- Tag tree -----------------------------------------------------------------


def test_opc_item_path_matches_the_driver_naming():
    assert opc_item_path("rtu-1", "ai", 4) == "ns=1;s=[rtu-1]AnalogInput4"
    assert opc_item_path("rtu-1", "bo", 0) == "ns=1;s=[rtu-1]BinaryOutput0"


def test_device_tag_folder_names_points_after_otsim():
    points = Outstations(OTSIM_APP, TOPOLOGY.get).points("rtu-1")
    folder = device_tag_folder({"name": "rtu-1", "points": points}, None)

    assert folder["name"] == "rtu-1"
    assert folder["tagType"] == "Folder"
    assert [f["name"] for f in folder["tags"]] == ["cap1", "671692", "_Diagnostics_"]
    tags = dict(leaves(folder))
    assert tags["cap1/voltage"] == {
        "name": "voltage",
        "tagType": "AtomicTag",
        "valueSource": "opc",
        "opcServer": "Ignition OPC UA Server",
        "opcItemPath": "ns=1;s=[rtu-1]AnalogInput0",
        "dataType": "Float8",
        "deadband": 0.0,
        "tooltip": "capacitor cap1",
        "documentation": "capacitor cap1 (ot-sim, DNP3 AnalogInput 0)",
        "readOnly": True,
    }
    setpt = tags["cap1/setpt"]
    assert setpt["opcItemPath"] == "ns=1;s=[rtu-1]AnalogOutput0"
    assert "readOnly" not in setpt
    assert tags["671692/status"]["dataType"] == "Boolean"
    assert tags["671692/status"]["opcItemPath"] == "ns=1;s=[rtu-1]BinaryInput0"
    assert tags["671692/controls"]["opcItemPath"] == "ns=1;s=[rtu-1]BinaryOutput0"
    assert tags["671692/voltage"]["opcItemPath"] == "ns=1;s=[rtu-1]AnalogInput4"


def test_device_tag_folder_adds_history():
    device = {"name": "rtu-1", "points": [point("ai", 0, "cap1", "voltage")]}
    tags = dict(leaves(device_tag_folder(device, history_properties("hp"))))
    tag = tags["cap1/voltage"]
    assert tag.items() >= history_properties("hp").items()
    assert tag["historyProvider"] == "hp"
    # driver diagnostics are not process data
    assert "historyEnabled" not in tags["_Diagnostics_/Hostname"]


def test_device_tag_folder_mirrors_driver_diagnostics():
    device = {"name": "rtu-1", "points": [point("ai", 0, "cap1", "voltage")]}
    tags = dict(leaves(device_tag_folder(device, None)))
    # the overview reads Hostname and Port from this folder, like discovery
    assert tags["_Diagnostics_/Hostname"]["opcItemPath"] == (
        "ns=1;s=[rtu-1][Diagnostics]/Hostname"
    )
    assert tags["_Diagnostics_/Port"]["dataType"] == "Int4"
    assert tags["_Diagnostics_/Status"]["readOnly"] is True


def test_reserved_diagnostics_name_is_rejected():
    device = {"name": "rtu-1", "points": [point("ai", 0, "_Diagnostics_", "v")]}
    with pytest.raises(ValueError, match="reserved"):
        device_tag_folder(device, None)


@pytest.mark.parametrize("bad", ["a.b", "a/b", "[x]", "", "x" * 256])
def test_invalid_otsim_names_are_rejected(bad):
    device = {"name": "rtu-1", "points": [point("ai", 0, bad, "voltage")]}
    with pytest.raises(
        ValueError, match=r"device 'rtu-1'.*not a valid Ignition tag name"
    ):
        device_tag_folder(device, None)
    device = {"name": "rtu-1", "points": [point("ai", 0, "cap1", bad)]}
    with pytest.raises(ValueError, match=r"ot-sim device 'cap1'.*not a valid"):
        device_tag_folder(device, None)


def test_duplicate_points_are_rejected_with_their_addresses():
    device = {
        "name": "rtu-1",
        "points": [point("ao", 0, "cap1", "setpt"), point("ao", 3, "cap1", "setpt")],
    }
    with pytest.raises(
        ValueError, match=r"served twice \(AnalogOutput0 and AnalogOutput3\).*discover"
    ):
        device_tag_folder(device, None)


def test_write_tag_tree_mapped_devices_need_no_sync(mock_app, tmp_path):
    devices = [{"name": "rtu-1", "points": [point("ai", 0, "cap1", "voltage")]}]
    mock_app._write_tag_tree(tmp_path, devices)
    (folder,) = json.loads((tmp_path / "tags.json").read_text())
    assert folder["name"] == "rtu-1"


def test_write_tag_tree_mixed_devices_scope_the_sync(mock_app, tmp_path):
    devices = [
        {"name": "rtu-1", "points": [point("ai", 0, "cap1", "voltage")]},
        {"name": "rtu-2", "points": None},
    ]
    mock_app._write_tag_tree(tmp_path, devices, historian=True)
    folder, sync = json.loads((tmp_path / "tags.json").read_text())
    assert folder["name"] == "rtu-1"
    assert dict(leaves(folder))["cap1/voltage"]["historyProvider"] == (
        HISTORY_PROVIDER_NAME
    )
    assert sync["name"] == TAG_SYNC_NAME
    script = sync["eventScripts"][0]["script"]
    assert script.startswith("\tmapped_devices = ['rtu-1']\n\thistory = {")
    assert f"'historyProvider': '{HISTORY_PROVIDER_NAME}'" in script


def test_write_tag_tree_without_devices_discovers_the_gateway(mock_app, tmp_path):
    mock_app._write_tag_tree(tmp_path, [])
    (sync,) = json.loads((tmp_path / "tags.json").read_text())
    assert sync["name"] == TAG_SYNC_NAME
    assert (
        "\tmapped_devices = []\n\thistory = None\n" in sync["eventScripts"][0]["script"]
    )
