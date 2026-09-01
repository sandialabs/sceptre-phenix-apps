"""Execute the generated gateway event against stateful tag-service doubles."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from phenix_apps.apps.ignition.app import HISTORY_PROVIDER_NAME, Ignition

ROOT = "[default]rtu-1"
HISTORY = {
    "historyEnabled": True,
    "historyProvider": HISTORY_PROVIDER_NAME,
    "sampleMode": "OnChange",
    "historicalDeadbandStyle": "Discrete",
    "historicalDeadbandMode": "Absolute",
    "historicalDeadband": 0.0,
    "historyTimeDeadband": 0,
    "historyMaxAge": 0,
}
GOOD = SimpleNamespace(isGood=lambda: True)
BAD = SimpleNamespace(isGood=lambda: False)


def point(name, kind="DATAVARIABLE"):
    return SimpleNamespace(
        getOpcItemPath=lambda: "ns=1;s=[rtu-1]" + name,
        getType=lambda: kind,
        getDataType=lambda: "class java.lang.Double",
    )


@pytest.fixture
def runtime(tmp_path):
    state = {}
    logger = Mock()
    system = Mock()
    system.util.getLogger.return_value = logger
    system.device.listDevices.return_value = SimpleNamespace(
        getRowCount=lambda: 1, getValueAt=lambda row, col: "rtu-1"
    )
    system.opc.browse.return_value = []

    def browse(parent, options):
        assert options == {"recursive": True}
        tags = [
            {
                "fullPath": path,
                "name": path.rsplit("/", 1)[-1],
                "hasChildren": config["tagType"] == "Folder",
                "tagType": config["tagType"],
                "valueSource": config.get("valueSource"),
            }
            for path, config in state.items()
            if path.startswith(parent + "/")
        ]
        return SimpleNamespace(getResults=lambda: tags)

    def configure(parent, tags, policy):
        assert policy == "m"
        for tag in tags:
            path = parent + ("" if parent.endswith("]") else "/") + tag["name"]
            state.setdefault(path, {}).update(
                {key: value for key, value in tag.items() if key != "tags"}
            )
            if "tags" in tag:
                configure(path, tag["tags"], policy)
        return [GOOD for _ in tags]

    def read(paths):
        values = []
        for path in paths:
            tag, prop = path.rsplit(".", 1)
            values.append(SimpleNamespace(value=state[tag].get(prop), quality=GOOD))
        return values

    system.tag.browse.side_effect = browse
    system.tag.configure.side_effect = configure
    system.tag.readBlocking.side_effect = read

    def run(historian=True):
        Ignition._write_tag_tree(tmp_path, historian=historian)
        (sync,) = json.loads((tmp_path / "tags.json").read_text())
        script = sync["eventScripts"][0]["script"]
        namespace = {"system": system}
        exec("def sync():\n" + script, namespace)
        namespace["sync"]()

    return SimpleNamespace(state=state, system=system, logger=logger, run=run)


def atomic(source="opc", **config):
    return {"tagType": "AtomicTag", "valueSource": source, **config}


def test_new_nested_points_receive_native_history(runtime):
    runtime.system.opc.browse.return_value = [
        point("Analog/Input0"),
        point("BinaryInput0"),
        point("[Diagnostics]/Count"),
        point("Folder", "OBJECT"),
        point("_TagSync_"),
    ]
    runtime.run()
    for name in ["Analog/Input0", "BinaryInput0", "_Diagnostics_/Count"]:
        config = runtime.state[ROOT + "/" + name]
        assert config.items() >= HISTORY.items()
        assert config["valueSource"] == "opc"
        assert config["dataType"] == "Float8"
    for config in runtime.state.values():
        if config["tagType"] == "Folder" or config["name"] == "_TagSync_":
            assert "historyEnabled" not in config
    assert ROOT + "/Folder" not in runtime.state
    runtime.logger.warn.assert_not_called()


def test_existing_points_get_history_without_clobbering_configuration(runtime):
    original = atomic(
        dataType="Float4",
        opcItemPath="custom-path",
        alarms=[{"name": "High", "setpointA": 100}],
        documentation="Operator notes",
        historyProvider="old-provider",
    )
    runtime.state[ROOT + "/AnalogInput0"] = original.copy()
    runtime.system.opc.browse.return_value = [point("AnalogInput0")]
    runtime.run()
    assert runtime.state[ROOT + "/AnalogInput0"] == {
        **original,
        "name": "AnalogInput0",
        **HISTORY,
    }
    runtime.system.tag.configure.assert_called_once_with(
        ROOT, [{"name": "AnalogInput0", **HISTORY}], "m"
    )


def test_history_is_reconciled_even_without_current_opc_points(runtime):
    runtime.state[ROOT + "/OfflinePoint"] = atomic()
    runtime.run()
    assert runtime.state[ROOT + "/OfflinePoint"]["historyEnabled"] is True


def test_existing_nested_history_updates_use_the_parent_folder(runtime):
    runtime.state[ROOT + "/Analog"] = {"tagType": "Folder", "documentation": "retained"}
    runtime.state[ROOT + "/Analog/Input0"] = atomic(
        historicalDeadbandMode="Percent",
        historyTimeDeadband=100,
        historyTimeDeadbandUnits="SEC",
        historyMaxAge=60,
        historyMaxAgeUnits="MIN",
    )
    runtime.run()
    runtime.system.tag.configure.assert_called_once_with(
        ROOT + "/Analog", [{"name": "Input0", **HISTORY}], "m"
    )
    assert runtime.state[ROOT + "/Analog"] == {
        "tagType": "Folder",
        "documentation": "retained",
    }
    tag = runtime.state[ROOT + "/Analog/Input0"]
    assert tag["historyTimeDeadbandUnits"] == "SEC"
    assert tag["historyMaxAgeUnits"] == "MIN"
    runtime.system.tag.browse.assert_called_once_with(ROOT, {"recursive": True})


def test_existing_non_opc_tags_and_folders_are_untouched(runtime):
    runtime.state.update(
        {
            ROOT + "/Memory": atomic("memory", value=42),
            ROOT + "/Expression": atomic("expr", expression="now()"),
            ROOT + "/Unknown": {"tagType": "AtomicTag"},
            ROOT + "/_TagSync_": atomic(),
            ROOT + "/Folder": {"tagType": "Folder"},
        }
    )
    runtime.system.opc.browse.return_value = [point("Memory")]
    before = {path: config.copy() for path, config in runtime.state.items()}
    runtime.run()
    assert runtime.state == before
    runtime.system.tag.configure.assert_not_called()
    runtime.system.tag.readBlocking.assert_not_called()


def test_later_discovery_does_not_restart_already_configured_history(runtime):
    runtime.system.opc.browse.return_value = [point("AnalogInput0")]
    runtime.run()
    runtime.system.tag.configure.reset_mock()
    runtime.run()
    runtime.system.tag.configure.assert_not_called()
    runtime.system.opc.browse.return_value.append(point("AnalogInput1"))
    runtime.run()
    assert runtime.state[ROOT + "/AnalogInput1"].items() >= HISTORY.items()
    runtime.system.tag.configure.assert_called_once()
    new_root = runtime.system.tag.configure.call_args.args[1][0]
    assert [tag["name"] for tag in new_root["tags"]] == ["AnalogInput1"]


def test_discovery_uses_paths_not_existing_point_count(runtime):
    runtime.state[ROOT + "/Unrelated"] = atomic("memory")
    runtime.system.opc.browse.return_value = [point("New")]
    runtime.run()
    assert runtime.state[ROOT + "/New"].items() >= HISTORY.items()


def test_perspective_only_imports_without_enabling_history(runtime):
    runtime.system.opc.browse.return_value = [point("AnalogInput0")]
    runtime.run(historian=False)
    assert "historyEnabled" not in runtime.state[ROOT + "/AnalogInput0"]
    runtime.system.tag.readBlocking.assert_not_called()
    runtime.system.tag.configure.reset_mock()
    runtime.run(historian=False)
    runtime.system.tag.configure.assert_not_called()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("results", [[], [BAD], [GOOD, BAD]])
def test_bad_or_incomplete_configuration_results_are_reported(
    runtime, existing, results
):
    runtime.system.opc.browse.return_value = [point("AnalogInput0")]
    if existing:
        runtime.state[ROOT + "/AnalogInput0"] = atomic()
    runtime.system.tag.configure.side_effect = None
    runtime.system.tag.configure.return_value = results
    runtime.run()
    runtime.logger.warn.assert_called_once()
    runtime.logger.info.assert_not_called()
    runtime.system.tag.configure.reset_mock()
    runtime.run()
    runtime.system.tag.configure.assert_called_once()


@pytest.mark.parametrize(
    "results",
    [[], [SimpleNamespace(value=None, quality=BAD)] * len(HISTORY)],
)
def test_bad_property_reads_report_and_retry_without_blind_updates(runtime, results):
    runtime.state[ROOT + "/Existing"] = atomic()
    runtime.system.tag.readBlocking.side_effect = None
    runtime.system.tag.readBlocking.return_value = results
    runtime.run()
    runtime.logger.warn.assert_called_once()
    runtime.system.tag.configure.assert_not_called()


def test_discovery_does_not_convert_an_existing_atomic_tag_to_a_folder(runtime):
    runtime.state[ROOT + "/Collision"] = atomic("memory", value=42)
    runtime.system.opc.browse.return_value = [point("Collision/Point")]
    runtime.run()
    assert runtime.state[ROOT + "/Collision"] == atomic("memory", value=42)
    runtime.system.tag.configure.assert_not_called()
    runtime.logger.warn.assert_called_once()


def test_reserved_device_name_cannot_replace_the_heartbeat(runtime):
    runtime.system.device.listDevices.return_value.getValueAt = lambda row, col: (
        "_TagSync_"
    )
    runtime.run()
    runtime.system.opc.browse.assert_not_called()
    runtime.system.tag.configure.assert_not_called()
    runtime.logger.warn.assert_called_once()
