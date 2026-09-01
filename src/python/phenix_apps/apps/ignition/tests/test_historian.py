"""Historian metadata and resource-generation contracts."""

import json
from itertools import product
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

import pytest
import yaml
from pydantic import ValidationError

from phenix_apps.apps.ignition.app import (
    GUEST_CLIENT_SCRIPT_DST,
    GUEST_DATABASE_DIR,
    GUEST_HISTORY_DIR,
    GUEST_PROJECTS_DIR,
    GUEST_RESOURCE_DIR,
    GUEST_TAG_DIR,
    HISTORY_PROVIDER_NAME,
    HistorianConfig,
    Ignition,
    IgnitionHostConfig,
)
from phenix_apps.apps.ignition.tests.test_ignition import _gateway, _nodes

pytestmark = pytest.mark.app_class(cls=Ignition, name="ignition")

CONNECTION = {
    "ip": "10.68.30.200",
    "user": "ignition",
    "database": "ignition_history",
}


def test_historian_defaults():
    config = HistorianConfig(ip=CONNECTION["ip"])
    assert config.port == 5432
    assert config.database == "ignition"
    assert config.user == "ignition"


def test_historian_dict_overrides():
    cfg = IgnitionHostConfig(
        historian={**CONNECTION, "port": "15432", "user": "historian"}
    )
    assert cfg.historian.port == 15432
    assert cfg.historian.user == "historian"
    assert cfg.historian.database == "ignition_history"


@pytest.mark.parametrize("value", [None, False])
def test_historian_disabled(value):
    assert IgnitionHostConfig(historian=value).historian is None
    assert IgnitionHostConfig().historian is None
    assert IgnitionHostConfig(gwbk="/backup.gwbk", historian=value).historian is None


def test_historian_true_has_actionable_error():
    with pytest.raises(ValidationError, match="supply ip"):
        IgnitionHostConfig(historian=True)


def test_historian_requires_ip():
    with pytest.raises(ValidationError, match="ip"):
        IgnitionHostConfig(historian={})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ip", ""),
        ("ip", "database.example"),
        ("ip", "10.0.0.999"),
        ("ip", "10.0.0.1/database"),
        ("user", None),
        ("database", None),
        ("port", 5432.5),
        ("port", None),
        ("driver", "MySQL"),
    ],
)
def test_historian_rejects_invalid_configuration(field, value):
    with pytest.raises(ValidationError) as caught:
        IgnitionHostConfig(historian={**CONNECTION, field: value})
    assert "input_value" not in str(caught.value)


def test_historian_gwbk_is_verbatim_and_error_does_not_log_input():
    with pytest.raises(
        ValidationError, match="cannot be combined with 'gwbk'"
    ) as caught:
        IgnitionHostConfig(gwbk="/backup.gwbk", historian=CONNECTION)
    assert "input_value" not in str(caught.value)


def test_native_resources_and_provider_linkage(mock_app, mocker):
    tree_injects = mocker.spy(mock_app, "_tree_injects")
    mock_app._write_historian(
        "OT-scada",
        Path(mock_app.app_dir) / "OT-scada",
        HistorianConfig(**CONNECTION),
    )
    tree_injects.assert_called_once_with(
        Path(mock_app.app_dir) / "OT-scada/historian", GUEST_RESOURCE_DIR
    )
    injects = {
        call.kwargs["inject"]["dst"]: Path(call.kwargs["inject"]["src"])
        for call in mock_app.add_inject.call_args_list
    }
    assert set(injects) == {
        f"{base}/{HISTORY_PROVIDER_NAME}/{filename}"
        for base in [GUEST_DATABASE_DIR, GUEST_HISTORY_DIR]
        for filename in ["config.json", "resource.json"]
    }
    db = json.loads(
        injects[f"{GUEST_DATABASE_DIR}/{HISTORY_PROVIDER_NAME}/config.json"].read_text()
    )
    history = json.loads(
        injects[f"{GUEST_HISTORY_DIR}/{HISTORY_PROVIDER_NAME}/config.json"].read_text()
    )
    assert db["driver"] == "PostgreSQL"
    assert db["translator"] == "POSTGRES"
    assert db["connectURL"] == "jdbc:postgresql://10.68.30.200:5432/ignition_history"
    assert db["username"] == CONNECTION["user"]
    assert db["connectionProps"] == ""
    assert history["profile"] == {"type": "SqlHistorian"}
    assert history["settings"]["database"] == HISTORY_PROVIDER_NAME
    assert set(history["settings"]) == {
        "database",
        "partition",
        "pruning",
        "staleMultiplier",
        "trackSce",
    }
    assert history["settings"]["pruning"]["enabled"] is False
    uuids = []
    for base in [GUEST_DATABASE_DIR, GUEST_HISTORY_DIR]:
        manifest = json.loads(
            injects[f"{base}/{HISTORY_PROVIDER_NAME}/resource.json"].read_text()
        )
        assert manifest["scope"] == "A"
        assert manifest["version"] == 1
        assert manifest["files"] == ["config.json"]
        assert manifest["attributes"]["enabled"] is True
        uuids.append(UUID(manifest["attributes"]["uuid"]))
        assert "lastModificationSignature" not in manifest["attributes"]
        assert "lastModification" not in manifest["attributes"]
    assert len(set(uuids)) == 2


@pytest.mark.parametrize(
    ("ip", "authority"),
    [("10.68.30.200", "10.68.30.200:15432"), ("2001:db8::1", "[2001:db8::1]:15432")],
)
def test_connection_details_are_json_and_jdbc_escaped(mock_app, ip, authority):
    user = 'quoted"\\user\n' + chr(0x2603)
    database = 'history/name?password=ignored&ssl=false#"\\ ' + chr(0x2603)
    cfg = HistorianConfig(ip=ip, port=15432, user=user, database=database)
    mock_app._write_historian("OT-scada", Path(mock_app.app_dir), cfg)
    config_path = (
        Path(mock_app.app_dir)
        / "historian/ignition/database-connection"
        / HISTORY_PROVIDER_NAME
        / "config.json"
    )
    config = json.loads(config_path.read_text())
    assert config["username"] == user
    url = urlsplit(config["connectURL"].removeprefix("jdbc:"))
    assert url.netloc == authority
    assert unquote(url.path[1:]) == database
    assert not url.query
    assert not url.fragment
    assert "password" not in config


def test_sample_yaml_matches_configuration():
    sample = yaml.safe_load(
        Path(__file__).with_name("test_ignition_input.yaml").read_text()
    )
    gateway = sample["spec"]["scenario"]["apps"][0]["hosts"][0]
    cfg = IgnitionHostConfig(**gateway["metadata"])
    assert cfg.historian == HistorianConfig(**CONNECTION)


@pytest.mark.parametrize(
    ("perspective", "api", "connected_rtus"),
    list(product([False, True], [False, True], [False, True])),
)
def test_historian_combinations_seed_tags_once(
    mock_app, mocker, perspective, api, connected_rtus
):
    log = mocker.patch("phenix_apps.apps.ignition.app.logger")
    seed = mocker.spy(mock_app, "_write_tag_tree")
    _nodes(
        mock_app,
        gateways=[
            _gateway(
                historian={"ip": CONNECTION["ip"]},
                perspective={"open_client": False} if perspective else False,
                api=api,
                connected_rtus=["rtu-1"] if connected_rtus else [],
            )
        ],
    )
    mock_app.extract_node_interface_ip.return_value = "10.68.30.201"

    mock_app.pre_start()

    seed.assert_called_once()
    log.warning.assert_not_called()
    injects = [call.kwargs["inject"] for call in mock_app.add_inject.call_args_list]
    assert all(Path(inject["src"]).is_file() for inject in injects)
    dsts = [inject["dst"] for inject in injects]
    assert len(dsts) == len(set(dsts))
    assert dsts.count(f"{GUEST_TAG_DIR}/tags.json") == 1
    assert dsts.count(f"{GUEST_TAG_DIR}/unary-resource.json") == 1
    assert GUEST_CLIENT_SCRIPT_DST not in dsts
    assert not any(dst.endswith(".ps1") for dst in dsts)
    assert f"{GUEST_DATABASE_DIR}/{HISTORY_PROVIDER_NAME}/config.json" in dsts
    assert f"{GUEST_HISTORY_DIR}/{HISTORY_PROVIDER_NAME}/config.json" in dsts
    assert (
        any(dst.startswith(f"{GUEST_PROJECTS_DIR}/hmi/") for dst in dsts) == perspective
    )
    assert any(dst.startswith(f"{GUEST_PROJECTS_DIR}/api/") for dst in dsts) == api
    tag_src = next(
        i["src"] for i in injects if i["dst"] == f"{GUEST_TAG_DIR}/tags.json"
    )
    (sync,) = json.loads(Path(tag_src).read_text())
    assert HISTORY_PROVIDER_NAME in sync["eventScripts"][0]["script"]
    assert "historyEnabled" not in sync


@pytest.mark.parametrize("api", [False, True])
def test_without_historian_or_perspective_does_not_seed_tags(mock_app, mocker, api):
    seed = mocker.spy(mock_app, "_write_tag_tree")
    _nodes(mock_app, gateways=[_gateway(connected_rtus=["rtu-1"], api=api)])
    mock_app.extract_node_interface_ip.return_value = "10.68.30.201"
    mock_app.pre_start()
    seed.assert_not_called()
