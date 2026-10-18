"""Contract tests for the Perspective command popup without an Ignition gateway."""

import ast
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
COMMANDS_CODE = TEMPLATES / "perspective/ignition/script-python/commands/code.py"
VIEWS = TEMPLATES / "perspective/com.inductiveautomation.perspective/views"
DO_POST = TEMPLATES / "api/com.inductiveautomation.webdev/resources/tags/doPost.py"
JYTHON_BUILTINS = {"basestring": str, "long": int}
FLOAT32_MAX = 3.4028234663852886e38
FLOAT64_MAX = 1.7976931348623157e308
REJECTED = object()

ANALOG_VALUES = [
    0,
    12.0,
    -12.0,
    1.025,
    -1.025,
    2**15 - 1,
    2**15,
    -(2**15),
    -(2**15) - 1,
    2**31 - 1,
    2**31,
    -(2**31),
    -(2**31) - 1,
    FLOAT32_MAX,
    FLOAT32_MAX * 2,
    int(FLOAT32_MAX),
    int(FLOAT32_MAX) + 1,
    2.0**-149,
    1e-50,
    FLOAT64_MAX,
    int(FLOAT64_MAX),
    int(FLOAT64_MAX) + 1,
    5e-324,
    10**1000,
    float("nan"),
    float("inf"),
    True,
    "1.025",
    None,
]


@pytest.fixture
def system():
    ignition = Mock(spec=["device", "dnp", "perspective"])
    ignition.device = Mock(spec=["listDevices"])
    dataset = Mock(spec=["getRowCount", "getValueAt"])
    dataset.getRowCount.return_value = 1
    dataset.getValueAt.return_value = "rtu-1"
    ignition.device.listDevices.return_value = dataset
    ignition.dnp = Mock(spec=["directOperateAnalog"])
    ignition.perspective = Mock(spec=["openPopup"])
    return ignition


@pytest.fixture
def commands(system):
    namespace = {"system": system, **JYTHON_BUILTINS}
    exec(compile(COMMANDS_CODE.read_text(), str(COMMANDS_CODE), "exec"), namespace)
    return namespace


@pytest.fixture
def do_post(system):
    namespace = {"system": system, **JYTHON_BUILTINS}
    exec(compile(DO_POST.read_text(), str(DO_POST), "exec"), namespace)
    return namespace["doPost"]


@pytest.fixture(scope="module")
def popup():
    return json.loads((VIEWS / "popups/sendCommand/view.json").read_text())


def children(container):
    return {c["meta"]["name"]: c for c in container["children"]}


@pytest.mark.parametrize(
    ("point", "command", "index"),
    [
        ("BinaryOutput3", "crob", 3),
        ("BinaryOutput/3", "crob", 3),
        ("AnalogOutput1", "analog", 1),
        ("AnalogOutput/12", "analog", 12),
        ("AnalogInput0", "crob", None),
        ("BinaryInput2", "crob", None),
        (None, "crob", None),
    ],
)
def test_open_popup_selects_command_from_point(commands, system, point, command, index):
    commands["openPopup"]("rtu-1", point)

    (call,) = system.perspective.openPopup.call_args_list
    assert call.args == ("command", "popups/sendCommand")
    params = call.kwargs["params"]
    assert params["deviceName"] == "rtu-1"
    assert params["command"] == command
    assert params.get("index") == index


@pytest.mark.parametrize("variation", [1, 2, 3, 4])
@pytest.mark.parametrize("value", ANALOG_VALUES)
def test_analog_value_matches_api_validation(
    commands, do_post, system, variation, value
):
    request = {
        "servletResponse": Mock(spec=["setStatus"]),
        "postData": {
            "deviceName": "rtu-1",
            "pointType": "analog",
            "index": 0,
            "variation": variation,
            "value": value,
        },
    }
    response = do_post(request, {})

    try:
        encoded = commands["analogValue"](value, variation)
    except ValueError:
        encoded = REJECTED

    if encoded is REJECTED:
        assert response["json"]["status"] == "error"
        system.dnp.directOperateAnalog.assert_not_called()
    else:
        assert response["json"]["status"] == "sent"
        system.dnp.directOperateAnalog.assert_called_once_with(
            "rtu-1", variation, 0, encoded
        )
        assert type(encoded) is type(response["json"]["value"])


def test_analog_value_returns_integers_for_integer_variations(commands):
    assert commands["analogValue"](12.0, 1) == 12
    assert type(commands["analogValue"](12.0, 2)) is int
    assert type(commands["analogValue"](12, 3)) is float


@pytest.mark.parametrize("variation", [0, 5, None])
def test_analog_value_rejects_unknown_variation(commands, variation):
    with pytest.raises(ValueError, match="variation"):
        commands["analogValue"](1.0, variation)


def test_popup_offers_analog_command(popup):
    root = children(popup["root"])
    dropdown = root["CommandDropdown"]
    assert {"label": "Analog Output", "value": "analog"} in dropdown["props"]["options"]
    assert popup["params"]["command"] == "crob"
    binding = dropdown["propConfig"]["props.value"]["binding"]
    assert binding["config"]["path"] == "view.params.command"

    analog = root["analogParams"]
    visible = analog["propConfig"]["meta.visible"]["binding"]["config"]["expression"]
    assert visible == "{../CommandDropdown.props.value} = 'analog'"
    fields = children(analog)
    assert {"IndexField", "ModeDropdown", "VariationDropdown", "ValueField"} <= set(
        fields
    )
    variation = fields["VariationDropdown"]["props"]
    assert [o["value"] for o in variation["options"]] == [1, 2, 3, 4]
    assert variation["value"] == 3


def test_popup_send_script_operates_analog(popup):
    button = children(popup["root"])["SendButton"]
    script = button["events"]["component"]["onActionPerformed"]["config"]["script"]
    assert "commands.analogValue(" in script
    assert "system.dnp.selectOperateAnalog(dev, variation, idx, value)" in script
    assert "system.dnp.directOperateAnalog(dev, variation, idx, value)" in script


def test_station_double_click_delegates_to_commands():
    station = json.loads((VIEWS / "station/view.json").read_text())
    table = children(station["root"])["pointsTable"]
    script = table["events"]["component"]["onRowDoubleClick"]["config"]["script"]
    # rows carry the OPC address, which names the output kind and index
    assert (
        "commands.openPopup(self.view.params.rtuName, event.value['address'])" in script
    )
    columns = [column["field"] for column in table["props"]["columns"]]
    assert columns == [
        "point",
        "description",
        "value",
        "quality",
        "timestamp",
        "address",
    ]
    transform = table["propConfig"]["props.data"]["binding"]["transforms"][0]["code"]
    assert '.Documentation" for p in paths' in transform
    assert '.OpcItemPath" for p in paths' in transform


def button_script(container, toolbar_name):
    toolbar = children(container)[toolbar_name]
    button = children(toolbar)["CommandButton"]
    return button["events"]["component"]["onActionPerformed"]["config"]["script"]


def test_station_button_opens_popup_for_selected_row():
    station = json.loads((VIEWS / "station/view.json").read_text())
    script = button_script(station["root"], "toolbar")
    # whole-row selection, so the selected row carries its OPC address
    table = children(station["root"])["pointsTable"]
    assert table["props"]["selection"]["enableColumnSelection"] is False
    assert 'self.parent.getSibling("pointsTable").props.selection.data' in script
    assert "address = rows[0]['address']" in script
    assert "commands.openPopup(self.view.params.rtuName, address)" in script


def test_overview_button_opens_popup_for_selected_rtu():
    overview = json.loads((VIEWS / "overview/view.json").read_text())
    (tab,) = overview["root"]["children"]
    tab_children = children(tab)
    assert list(tab_children) == ["toolbar", "Overview"]
    assert (
        tab_children["Overview"]["props"]["selection"]["enableColumnSelection"] is False
    )
    script = button_script(tab, "toolbar")
    assert "rtu = rows[0]['rtu']" in script
    assert "commands.openPopup(rtu)" in script


def test_scripts_avoid_f_strings(popup):
    # perspective scripts run under the gateway's jython 2.7
    station = json.loads((VIEWS / "station/view.json").read_text())
    overview = json.loads((VIEWS / "overview/view.json").read_text())
    button = children(popup["root"])["SendButton"]
    scripts = [
        button["events"]["component"]["onActionPerformed"]["config"]["script"],
        button_script(station["root"], "toolbar"),
        button_script(overview["root"]["children"][0], "toolbar"),
    ]
    sources = [COMMANDS_CODE.read_text()] + ["def handler():\n" + s for s in scripts]
    for source in sources:
        tree = ast.parse(source)
        assert not any(isinstance(node, ast.JoinedStr) for node in ast.walk(tree))
