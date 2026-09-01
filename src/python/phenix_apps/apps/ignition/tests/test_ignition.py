"""Unit tests for the ignition app."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.ignition.app import (
    API_PROJECT_NAME,
    GATEWAY_TYPE,
    GUEST_CLIENT_SCRIPT_DST,
    GUEST_DEVICE_DIR,
    GUEST_GWBK_SCRIPT_DST,
    GUEST_PROJECTS_DIR,
    GUEST_TAG_DIR,
    PERSPECTIVE_TYPE,
    ApiConfig,
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
    mock_app.app_dir = Path(mock_app.app_dir)
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

    # device resources go straight into the gateway's data tree pre-boot;
    # nothing is staged and no boot script is needed
    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert dsts == [
        f"{GUEST_DEVICE_DIR}/rtu-1/config.json",
        f"{GUEST_DEVICE_DIR}/rtu-1/resource.json",
    ]
    host_files = (Path(mock_app.app_dir) / "OT-scada").iterdir()
    assert not [path for path in host_files if path.suffix == ".ps1"]


def test_no_rtus_and_no_gwbk_skips_host(mock_app, mocker):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    _nodes(mock_app, gateways=[_gateway()])

    mock_app.pre_start()

    mock_app.add_inject.assert_not_called()
    log.warning.assert_called_once()


def test_api_only_does_not_skip_host(mock_app, mocker):
    """api alone (no connected_rtus, no gwbk) is a valid gateway config"""
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    _nodes(mock_app, gateways=[_gateway(api=True)])

    mock_app.pre_start()

    log.warning.assert_not_called()
    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert dsts
    assert all(d.startswith(f"{GUEST_PROJECTS_DIR}/{API_PROJECT_NAME}/") for d in dsts)


# --- gwbk restore ------------------------------------------------------------


def test_pre_start_gwbk_injects_backup_verbatim(mock_app, tmp_path):
    backup = tmp_path / "base.gwbk"
    backup.write_bytes(b"opaque-zip-bytes")
    _nodes(mock_app, gateways=[_gateway(gwbk=str(backup))])

    mock_app.pre_start()

    injects = [c.kwargs["inject"] for c in mock_app.add_inject.call_args_list]
    assert injects[0] == {"src": str(backup), "dst": "/phenix/ignition/restore.gwbk"}
    assert injects[1]["dst"] == GUEST_GWBK_SCRIPT_DST
    assert len(injects) == 2

    with open(f"{mock_app.app_dir}/OT-scada/98-ignition.ps1") as f:
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


# --- API config models --------------------------------------------------------


def test_api_bool_shorthand_uses_defaults():
    assert IgnitionHostConfig(api=True).api == ApiConfig(auth=False, roles=[])


def test_api_false_means_disabled():
    assert IgnitionHostConfig(api=False).api is None
    assert IgnitionHostConfig().api is None


def test_api_dict_overrides():
    cfg = IgnitionHostConfig(
        api={
            "auth": True,
            "require_https": True,
            "roles": ["Administrator"],
            "user_source": "range",
        }
    )
    assert cfg.api.auth is True
    assert cfg.api.require_https is True
    assert cfg.api.roles == ["Administrator"]
    assert cfg.api.user_source == "range"


def test_api_user_source_defaults():
    assert ApiConfig().user_source == "default"
    assert ApiConfig().require_https is False


def test_api_without_connected_rtus_is_allowed():
    # unlike perspective, the api browses devices live and needs no rtus
    cfg = IgnitionHostConfig(api=True)
    assert cfg.api == ApiConfig()
    assert cfg.connected_rtus == []


def test_api_with_gwbk_raises():
    with pytest.raises(ValidationError, match="cannot be combined with 'gwbk'"):
        IgnitionHostConfig(gwbk="/x/base.gwbk", api=True)


# --- Tag tree -----------------------------------------------------------------


def test_write_tag_tree_seeds_sync_tag(mock_app, tmp_path):
    tags_dir = tmp_path / "tags"

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
    assert 'merge_tags("[default]", [root])' in script
    assert 'system.tag.configure(parent, tags, "m")' in script
    # the browse also returns folder (OBJECT) nodes, which must not become tags
    assert 'str(p.getType()) == "DATAVARIABLE"' in script
    # browse reports java classes, tags need Ignition type names
    assert '"Double": "Float8"' in script
    # driver diagnostics browse as "[Diagnostics]"; brackets are illegal in
    # tag names and must sanitize to the "_Diagnostics_" the views read
    assert 'replace("[", "_").replace("]", "_")' in script
    # runs under the gateway's jython 2.7: no f-strings
    assert 'f"' not in script


# --- Perspective project ------------------------------------------------------


def test_write_perspective_project_patches_title_and_tabs(mock_app, tmp_path):
    project_dir = tmp_path / "project" / "myhmi"

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

    for name in ("overview", "station", "popups/sendCommand"):
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


def test_pre_start_perspective_injects_files_into_data_tree(mock_app):
    _perspective_setup(mock_app)

    mock_app.pre_start()

    injects = [c.kwargs["inject"] for c in mock_app.add_inject.call_args_list]
    # per-file injects only — a directory dst that already existed in the
    # image would nest the copy one level too deep
    assert all(Path(i["src"]).is_file() for i in injects)

    dsts = [i["dst"] for i in injects]
    project = f"{GUEST_PROJECTS_DIR}/hmi"
    views = f"{project}/com.inductiveautomation.perspective/views"
    for dst in (
        f"{GUEST_DEVICE_DIR}/rtu-1/config.json",
        f"{project}/project.json",
        f"{views}/overview/view.json",
        f"{views}/station/view.json",
        f"{views}/popups/sendCommand/view.json",
        f"{GUEST_TAG_DIR}/tags.json",
        f"{GUEST_TAG_DIR}/unary-resource.json",
    ):
        assert dst in dsts
    assert dsts.count(GUEST_CLIENT_SCRIPT_DST) == 1  # the open_client script

    by_dst = {i["dst"]: i["src"] for i in injects}
    with open(by_dst[f"{project}/project.json"]) as f:
        assert json.load(f)["title"] == "hmi"
    with open(by_dst[f"{GUEST_TAG_DIR}/tags.json"]) as f:
        assert json.load(f)[0]["name"] == "_TagSync_"


def test_gateway_open_client_points_at_localhost(mock_app):
    _perspective_setup(mock_app)

    mock_app.pre_start()

    script_path = f"{mock_app.app_dir}/OT-scada/99-ignition-perspective.ps1"
    with open(script_path, newline="") as f:
        script = f.read()
    assert "\r\n" in script
    assert "firefox.exe" in script
    assert "'http://localhost:8088/data/perspective/client/hmi'" in script


def test_open_client_false_skips_gateway_pop(mock_app):
    _perspective_setup(mock_app, project="hmi", open_client=False)

    mock_app.pre_start()

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert GUEST_CLIENT_SCRIPT_DST not in dsts
    assert not (
        Path(mock_app.app_dir) / "OT-scada/99-ignition-perspective.ps1"
    ).exists()


def test_perspective_project_name_in_inject_paths(mock_app):
    _perspective_setup(mock_app, project="nera")

    mock_app.pre_start()

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert f"{GUEST_PROJECTS_DIR}/nera/project.json" in dsts
    assert not any("/hmi/" in d for d in dsts)


# --- Perspective client hosts -------------------------------------------------


def test_perspective_client_infers_single_gateway(mock_app):
    _perspective_setup(mock_app, clients=[_client()])
    ips = {"rtu-1": "10.68.30.201", "OT-scada": "10.68.30.11"}
    mock_app.extract_node_interface_ip.side_effect = lambda h, i: ips[h]

    mock_app.pre_start()

    mock_app.extract_node_interface_ip.assert_any_call("OT-scada", None)
    with open(f"{mock_app.app_dir}/hmi-1/99-ignition-perspective.ps1", newline="") as f:
        script = f.read()
    assert "\r\n" in script
    assert "firefox.exe" in script
    assert "http://10.68.30.11:8088/data/perspective/client/hmi" in script

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert dsts.count(GUEST_CLIENT_SCRIPT_DST) == 2  # gateway + hmi-1 scripts


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


# --- API project --------------------------------------------------------------


def _api_tags(project_dir):
    return f"{project_dir}/com.inductiveautomation.webdev/resources/tags"


def _api_config(project_dir):
    with open(f"{_api_tags(project_dir)}/config.json") as f:
        return json.load(f)


def test_write_api_project_patches_post_auth(mock_app, tmp_path):
    project_dir = tmp_path / "project" / "api"

    mock_app._write_api_project(
        project_dir,
        ApiConfig(
            auth=True,
            require_https=True,
            roles=["Operator", "Admin"],
            user_source="range",
        ),
    )

    post = _api_config(project_dir)["doPost"]
    assert post["require-auth"] is True
    assert post["require-https"] is True
    assert post["required-roles"] == "Operator,Admin"
    assert post["user-source"] == "range"
    # reads stay open regardless of auth
    assert _api_config(project_dir)["doGet"]["require-auth"] is False
    assert _api_config(project_dir)["doGet"]["require-https"] is False

    for method in ("doGet", "doPost"):
        with open(f"{_api_tags(project_dir)}/{method}.py") as f:
            code = f.read()
        assert f"def {method}" in code
        # the resource runs under the gateway's jython 2.7: no f-strings
        assert 'f"' not in code


def test_write_api_project_auth_defaults_off(mock_app, tmp_path):
    project_dir = tmp_path / "project" / "api"

    mock_app._write_api_project(project_dir, ApiConfig())

    post = _api_config(project_dir)["doPost"]
    assert post["require-auth"] is False
    assert post["require-https"] is False
    assert post["required-roles"] == ""
    assert post["user-source"] == ""


def test_write_api_project_https_without_auth(mock_app, tmp_path):
    project_dir = tmp_path / "project" / "api"

    mock_app._write_api_project(project_dir, ApiConfig(require_https=True))

    post = _api_config(project_dir)["doPost"]
    assert post["require-https"] is True
    assert post["require-auth"] is False


# --- API end-to-end -----------------------------------------------------------


def test_pre_start_api_injects_files_into_data_tree(mock_app):
    _nodes(
        mock_app,
        gateways=[
            _gateway(
                connected_rtus=["rtu-1"],
                api={"auth": True, "require_https": True, "roles": ["Operator"]},
            )
        ],
    )
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    mock_app.pre_start()

    injects = [c.kwargs["inject"] for c in mock_app.add_inject.call_args_list]
    # per-file injects only, matching the perspective/device convention
    assert all(Path(i["src"]).is_file() for i in injects)

    dsts = [i["dst"] for i in injects]
    project = f"{GUEST_PROJECTS_DIR}/{API_PROJECT_NAME}"
    tags = f"{project}/com.inductiveautomation.webdev/resources/tags"
    for dst in (
        f"{project}/project.json",
        f"{tags}/resource.json",
        f"{tags}/config.json",
        f"{tags}/doGet.py",
        f"{tags}/doPost.py",
    ):
        assert dst in dsts

    by_dst = {i["dst"]: i["src"] for i in injects}
    with open(by_dst[f"{tags}/config.json"]) as f:
        post = json.load(f)["doPost"]
    assert post["require-auth"] is True
    assert post["require-https"] is True
    assert post["required-roles"] == "Operator"


def test_perspective_and_api_together(mock_app):
    _nodes(
        mock_app,
        gateways=[_gateway(connected_rtus=["rtu-1"], perspective=True, api=True)],
    )
    mock_app.extract_node_interface_ip.return_value = "10.68.30.11"

    mock_app.pre_start()

    dsts = [c.kwargs["inject"]["dst"] for c in mock_app.add_inject.call_args_list]
    assert any(d.startswith(f"{GUEST_PROJECTS_DIR}/hmi/") for d in dsts)
    assert any(d.startswith(f"{GUEST_PROJECTS_DIR}/{API_PROJECT_NAME}/") for d in dsts)
