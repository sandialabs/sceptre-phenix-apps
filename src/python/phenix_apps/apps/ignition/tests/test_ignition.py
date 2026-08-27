"""Unit tests for the ignition app."""

import json
from uuid import UUID

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.ignition.app import (
    GATEWAY_TYPE,
    GUEST_CLIENT_URL_DST,
    GUEST_STARTUP_DST,
    PERSPECTIVE_TYPE,
    Ignition,
    IgnitionHostConfig,
    PerspectiveConfig,
    RtuDeviceConfig,
)

pytestmark = pytest.mark.app_class(cls=Ignition, name="ignition")


def _gateway(hostname="OT-scada", **metadata):
    metadata.setdefault("type", "gateway")
    return Box({"hostname": hostname, "metadata": metadata})


def _client(hostname="hmi-1", **metadata):
    metadata.setdefault("type", "perspective")
    return Box({"hostname": hostname, "metadata": metadata})


def _nodes(mock_app, gateways=(), clients=()):
    """pre_start extracts gateway and perspective nodes separately."""
    mapping = {GATEWAY_TYPE: list(gateways), PERSPECTIVE_TYPE: list(clients)}
    mock_app.extract_nodes_type.side_effect = lambda t, *a: mapping.get(t, [])


# --- Config models -----------------------------------------------------------


def test_connected_rtus_accepts_plain_strings():
    cfg = IgnitionHostConfig(
        connected_rtus=["rtu-1", {"hostname": "rtu-2", "port": 20001}]
    )
    assert cfg.connected_rtus[0] == RtuDeviceConfig(hostname="rtu-1")
    assert cfg.connected_rtus[1].port == 20001


def test_rtu_defaults_match_tmw_conventions():
    rtu = RtuDeviceConfig(hostname="rtu-1")
    assert (rtu.port, rtu.source_address, rtu.destination_address) == (20000, 1, 1024)
    assert rtu.interface is None
    assert rtu.resolved_name == "rtu-1"


def test_rtu_name_override_wins():
    assert RtuDeviceConfig(hostname="rtu-1", name="farm-controller").resolved_name == (
        "farm-controller"
    )


def test_host_config_defaults():
    cfg = IgnitionHostConfig()
    assert cfg.gwbk is None
    assert cfg.connected_rtus == []


def test_gwbk_with_connected_rtus_raises():
    with pytest.raises(ValidationError, match="cannot be combined"):
        IgnitionHostConfig(gwbk="/x/base.gwbk", connected_rtus=["rtu-1"])


# --- RTU resolution ----------------------------------------------------------


def test_resolve_devices_uses_topology_ip(mock_app):
    mock_app.extract_node_interface_ip.return_value = "10.68.30.201"

    devices = mock_app._resolve_devices(
        [RtuDeviceConfig(hostname="rtu-1", interface="eth1")]
    )

    mock_app.extract_node_interface_ip.assert_called_once_with("rtu-1", "eth1")
    assert devices == [
        {
            "name": "rtu-1",
            "ip": "10.68.30.201",
            "port": 20000,
            "source_address": 1,
            "destination_address": 1024,
        }
    ]


def test_resolve_devices_missing_node_dryrun_placeholder(mock_app, mocker):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    mock_app.extract_node_interface_ip.return_value = None

    devices = mock_app._resolve_devices([RtuDeviceConfig(hostname="ghost")])

    assert devices[0]["ip"] == "127.0.0.1"
    log.warning.assert_called_once()


def test_resolve_devices_missing_node_raises_non_dryrun(mock_app):
    mock_app.dryrun = False
    mock_app.extract_node_interface_ip.return_value = None

    with pytest.raises(ValueError, match="no addressed interface"):
        mock_app._resolve_devices([RtuDeviceConfig(hostname="ghost")])


def test_duplicate_device_names_raise(mock_app):
    device = {"name": "rtu-1", "ip": "10.0.0.1"}
    with pytest.raises(ValueError, match="Duplicate device name"):
        mock_app._validate_unique_names([device, {**device, "ip": "10.0.0.2"}])


# --- Device rendering (connected_rtus) ---------------------------------------


def test_pre_start_renders_and_injects_devices(mock_app):
    _nodes(mock_app, gateways=[_gateway(connected_rtus=["rtu-1"])])
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    mock_app.pre_start()

    with open(f"{mock_app.app_dir}/OT-scada/devices/rtu-1/config.json") as f:
        config = json.load(f)
    assert config["profile"]["type"] == "com.inductiveautomation.Dnp3DeviceType"
    assert config["settings"]["connectivity"]["hostname"] == "10.68.30.11"
    assert config["settings"]["connectivity"]["port"] == 20000
    assert config["settings"]["connectivity"]["destinationAddress"] == 1024
    # Non-connectivity settings pass through from the shipped template.
    assert "dataAcquisition" in config["settings"]

    with open(f"{mock_app.app_dir}/OT-scada/devices/rtu-1/resource.json") as f:
        resource = json.load(f)
    UUID(resource["attributes"]["uuid"])  # fresh, well-formed uuid
    assert resource["attributes"]["lastModification"]["actor"] == "phenix"
    assert resource["attributes"]["enabled"] is True
    # Signature is kept verbatim from the captured template, not recomputed.
    assert resource["attributes"]["lastModificationSignature"]

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert dsts == [
        "/phenix/ignition/devices/rtu-1/config.json",
        "/phenix/ignition/devices/rtu-1/resource.json",
        GUEST_STARTUP_DST,
    ]


def test_boot_script_contents_device_mode(mock_app):
    _nodes(mock_app, gateways=[_gateway(connected_rtus=["rtu-1"])])
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    mock_app.pre_start()

    with open(f"{mock_app.app_dir}/OT-scada/99-ignition.ps1", newline="") as f:
        script = f.read()
    assert "\r\n" in script
    assert "% if" not in script  # no leftover mako syntax
    assert "Test-Path $staged" in script
    assert "Stop-Service -Name Ignition" in script
    assert "Start-Service -Name Ignition" in script
    assert "Copy-Item" in script
    assert "gwcmd" not in script


def test_no_rtus_and_no_gwbk_skips_host(mock_app, mocker):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    _nodes(mock_app, gateways=[_gateway()])

    mock_app.pre_start()

    mock_app.add_inject.assert_not_called()
    log.warning.assert_called_once()


# --- gwbk restore ------------------------------------------------------------


def test_pre_start_gwbk_injects_backup_verbatim(mock_app, tmp_path):
    backup = tmp_path / "base.gwbk"
    backup.write_bytes(b"opaque-zip-bytes")
    _nodes(mock_app, gateways=[_gateway(gwbk=str(backup))])

    mock_app.pre_start()

    injects = [c.kwargs["inject"] for c in mock_app.add_inject.call_args_list]
    assert injects[0] == {"src": str(backup), "dst": "/phenix/ignition/restore.gwbk"}
    assert injects[1]["dst"] == GUEST_STARTUP_DST
    assert len(injects) == 2

    with open(f"{mock_app.app_dir}/OT-scada/99-ignition.ps1") as f:
        script = f.read()
    assert "gwcmd.bat" in script
    assert "-s $staged -m" in script
    assert "Copy-Item" not in script


def test_gwbk_missing_dryrun_warns_and_skips(mock_app, mocker, tmp_path):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    _nodes(mock_app, gateways=[_gateway(gwbk=str(tmp_path / "nope.gwbk"))])

    mock_app.pre_start()

    mock_app.add_inject.assert_not_called()
    log.warning.assert_called_once()


def test_gwbk_missing_raises_non_dryrun(mock_app, tmp_path):
    mock_app.dryrun = False
    _nodes(mock_app, gateways=[_gateway(gwbk=str(tmp_path / "nope.gwbk"))])

    with pytest.raises(ValueError, match="not found"):
        mock_app.pre_start()


# --- Perspective config models -----------------------------------------------


def test_perspective_bool_shorthand_uses_defaults():
    cfg = IgnitionHostConfig(connected_rtus=["rtu-1"], perspective=True)
    assert cfg.perspective == PerspectiveConfig(project="hmi", open_client=True)


def test_perspective_false_means_disabled():
    assert IgnitionHostConfig(perspective=False).perspective is None
    assert IgnitionHostConfig().perspective is None


def test_perspective_dict_overrides():
    cfg = IgnitionHostConfig(
        connected_rtus=["rtu-1"],
        perspective={"project": "nera", "open_client": False},
    )
    assert cfg.perspective.project == "nera"
    assert cfg.perspective.open_client is False


def test_perspective_project_name_validated():
    with pytest.raises(ValidationError, match="project names"):
        IgnitionHostConfig(connected_rtus=["rtu-1"], perspective={"project": "a b!"})


def test_perspective_with_gwbk_raises():
    with pytest.raises(ValidationError, match="cannot be combined with 'gwbk'"):
        IgnitionHostConfig(gwbk="/x/base.gwbk", perspective=True)


# --- Tag tree -----------------------------------------------------------------


def test_write_tag_tree_seeds_sync_tag(mock_app, tmp_path):
    tags_dir = str(tmp_path / "tags")

    mock_app._write_tag_tree(tags_dir)

    with open(f"{tags_dir}/unary-resource.json") as f:
        resource = json.load(f)
    assert resource["files"] == ["tags.json"]
    assert resource["scope"] == "G"

    with open(f"{tags_dir}/tags.json") as f:
        (tag,) = json.load(f)
    # a non-folder root tag: the overview table only lists folders, so the
    # heartbeat never shows up as an RTU row
    assert tag["name"] == "_TagSync_"
    assert tag["tagType"] == "AtomicTag"
    assert tag["valueSource"] == "expr"
    assert tag["expression"] == "now()"
    assert (tag["executionMode"], tag["executionRate"]) == ("FixedRate", 30000)

    (event,) = tag["eventScripts"]
    assert event["eventid"] == "valueChanged"
    script = event["script"]
    # the script mirrors each device's OPC browse tree into [default]
    assert "system.device.listDevices()" in script
    assert 'system.opc.browse(opcServer="Ignition OPC UA Server"' in script
    assert 'system.tag.configure("[default]", [root], "m")' in script
    # runs under the gateway's jython 2.7: no f-strings
    assert 'f"' not in script


# --- Perspective project ------------------------------------------------------


def test_write_perspective_project_patches_title_and_tabs(mock_app, tmp_path):
    project_dir = str(tmp_path / "project" / "myhmi")

    mock_app._write_perspective_project(project_dir, "myhmi", ["rtu-1", "rtu-2"])

    with open(f"{project_dir}/project.json") as f:
        assert json.load(f)["title"] == "myhmi"

    views = f"{project_dir}/com.inductiveautomation.perspective/views"
    with open(f"{views}/overview/view.json") as f:
        view = json.load(f)
    root = view["root"]
    assert root["props"]["tabs"] == ["Overview", "rtu-1", "rtu-2"]
    embeds = root["children"][1:]
    assert [e["props"]["params"]["rtuName"] for e in embeds] == ["rtu-1", "rtu-2"]
    assert all(e["props"]["path"] == "station" for e in embeds)
    assert [e["position"]["tabIndex"] for e in embeds] == [1, 2]

    # the repeatable station view ships verbatim, parameterized at runtime
    with open(f"{views}/station/view.json") as f:
        station = json.load(f)
    assert station["params"] == {"rtuName": ""}

    for name in ("overview", "station", "popups/sendCrob"):
        with open(f"{views}/{name}/resource.json") as f:
            assert json.load(f)["files"] == ["view.json"]


# --- Perspective end-to-end ---------------------------------------------------


def _perspective_setup(mock_app, clients=(), **perspective):
    _nodes(
        mock_app,
        gateways=[_gateway(connected_rtus=["rtu-1"], perspective=perspective or True)],
        clients=clients,
    )
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"


def test_pre_start_perspective_stages_one_directory_inject(mock_app):
    _perspective_setup(mock_app)

    mock_app.pre_start()

    injects = [c.kwargs["inject"] for c in mock_app.add_inject.call_args_list]
    dsts = [i["dst"] for i in injects]
    assert dsts == [
        "/phenix/ignition/devices/rtu-1/config.json",
        "/phenix/ignition/devices/rtu-1/resource.json",
        "/phenix/ignition/perspective",
        GUEST_CLIENT_URL_DST,
        GUEST_STARTUP_DST,
    ]

    stage = injects[2]["src"]
    assert stage == f"{mock_app.app_dir}/OT-scada/perspective"
    with open(f"{stage}/project/hmi/project.json") as f:
        assert json.load(f)["title"] == "hmi"
    with open(f"{stage}/tags/tags.json") as f:
        assert json.load(f)[0]["name"] == "_TagSync_"


def test_gateway_client_url_points_at_localhost(mock_app):
    _perspective_setup(mock_app)

    mock_app.pre_start()

    with open(f"{mock_app.app_dir}/OT-scada/perspective-client.url", newline="") as f:
        url = f.read()
    assert "URL=http://localhost:8088/data/perspective/client/hmi\r\n" in url


def test_open_client_false_skips_gateway_url(mock_app):
    _perspective_setup(mock_app, project="hmi", open_client=False)

    mock_app.pre_start()

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert GUEST_CLIENT_URL_DST not in dsts


def test_boot_script_contents_perspective_mode(mock_app):
    _perspective_setup(mock_app, project="nera")

    mock_app.pre_start()

    with open(f"{mock_app.app_dir}/OT-scada/99-ignition.ps1", newline="") as f:
        script = f.read()
    assert "% if" not in script
    assert "$stagedHmi" in script
    assert "data\\projects\\nera" in script
    assert "tag-definition\\default" in script
    assert "gwcmd" not in script


def test_boot_script_device_mode_has_no_perspective_block(mock_app):
    _nodes(mock_app, gateways=[_gateway(connected_rtus=["rtu-1"])])
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    mock_app.pre_start()

    with open(f"{mock_app.app_dir}/OT-scada/99-ignition.ps1") as f:
        assert "$stagedHmi" not in f.read()


# --- Perspective client hosts -------------------------------------------------


def test_perspective_client_infers_single_gateway(mock_app):
    _perspective_setup(mock_app, clients=[_client()])
    ips = {"rtu-1": "10.68.30.201", "OT-scada": "10.68.30.11"}
    mock_app.extract_node_interface_ip.side_effect = lambda h, i: ips[h]

    mock_app.pre_start()

    mock_app.extract_node_interface_ip.assert_any_call("OT-scada", None)
    with open(f"{mock_app.app_dir}/hmi-1/perspective-client.url", newline="") as f:
        url = f.read()
    assert "URL=http://10.68.30.11:8088/data/perspective/client/hmi\r\n" in url

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert dsts.count(GUEST_CLIENT_URL_DST) == 2  # gateway console + hmi-1


def test_perspective_client_without_gateway_raises(mock_app):
    _nodes(mock_app, clients=[_client()])

    with pytest.raises(ValueError, match="found 0 perspective-enabled"):
        mock_app.pre_start()


def test_perspective_client_ambiguous_gateways_raise(mock_app):
    _nodes(
        mock_app,
        gateways=[
            _gateway("gw-1", connected_rtus=["rtu-1"], perspective=True),
            _gateway("gw-2", connected_rtus=["rtu-1"], perspective=True),
        ],
        clients=[_client()],
    )
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    with pytest.raises(ValueError, match="found 2 perspective-enabled"):
        mock_app.pre_start()


def test_perspective_client_explicit_unknown_gateway_raises(mock_app):
    _perspective_setup(mock_app, clients=[_client(connected_gateway="nope")])

    with pytest.raises(ValueError, match="not a perspective-enabled gateway"):
        mock_app.pre_start()
