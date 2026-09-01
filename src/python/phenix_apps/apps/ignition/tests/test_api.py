"""Contract tests for the WebDev handlers without an Ignition gateway."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest

API_DIRECTORY = (
    Path(__file__).resolve().parent.parent
    / "templates/api/com.inductiveautomation.webdev/resources/tags"
)
OPC_SERVER = "Ignition OPC UA Server"
DEVICE = "rtu-1"
OTHER_DEVICE = "RTU 2"
FLOAT32_MAX = 3.4028234663852886e38
FLOAT64_MAX = 1.7976931348623157e308
BINARY_DEFAULTS = {"tcc": 1, "opType": 3, "count": 1, "onTime": 1000, "offTime": 1000}
MISSING = object()


def device_dataset(names):
    columns = ["Name", "Driver", "State"]
    rows = [[name, "DNP3", "Connected"] for name in names]
    dataset = Mock(spec=["getRowCount", "getValueAt"])
    dataset.getRowCount.return_value = len(rows)
    dataset.getValueAt.side_effect = lambda row, column: rows[row][
        columns.index(column)
    ]
    return dataset


def browse_element(path, element_type="DATAVARIABLE"):
    element = Mock(spec=["getType", "getOpcItemPath"])
    kind = MagicMock(spec=["toString", "__str__"])
    kind.toString.return_value = element_type
    kind.__str__.return_value = element_type
    element.getType.return_value = kind
    element.getOpcItemPath.return_value = path
    return element


def qualified_value(value, quality, timestamp):
    qualified = Mock(spec=["getValue", "getQuality", "getTimestamp"])
    qualified.getValue.return_value = value
    quality_code = MagicMock(spec=["__str__"])
    quality_code.__str__.return_value = quality
    qualified.getQuality.return_value = quality_code
    qualified.getTimestamp.return_value.getTime.return_value = timestamp
    return qualified


@pytest.fixture
def system():
    ignition = Mock(spec=["device", "dnp", "opc", "tag"])
    ignition.device = Mock(spec=["listDevices"])
    ignition.device.listDevices.return_value = device_dataset([DEVICE, OTHER_DEVICE])
    ignition.dnp = Mock(spec=["directOperateAnalog", "directOperateBinary"])
    ignition.dnp.directOperateAnalog.return_value = None
    ignition.dnp.directOperateBinary.return_value = None
    ignition.opc = Mock(spec=["browse", "readValues"])
    ignition.opc.browse.return_value = []
    ignition.opc.readValues.return_value = []
    ignition.tag = Mock()
    return ignition


@pytest.fixture(scope="module")
def handler_code():
    return {
        name: compile(
            (API_DIRECTORY / f"{name}.py").read_text(),
            str(API_DIRECTORY / f"{name}.py"),
            "exec",
        )
        for name in ("doPost", "doGet")
    }


@pytest.fixture
def handlers(handler_code, system):
    loaded = {}
    for name, code in handler_code.items():
        namespace = {"system": system, "basestring": str, "long": int}
        exec(code, namespace)
        loaded[name] = namespace[name]
    return SimpleNamespace(**loaded)


@pytest.fixture
def request_factory():
    def make_request(*, body=MISSING, params=None):
        request = {
            "servletResponse": Mock(spec=["setStatus"]),
            "params": {} if params is None else params,
        }
        if body is not MISSING:
            request["postData"] = body
        return request

    return make_request


@pytest.fixture(params=["analog", "binary"])
def post_body(request):
    body = {"deviceName": DEVICE, "pointType": request.param, "index": 1}
    if request.param == "analog":
        body["value"] = 1.025
    return body


@pytest.fixture
def readings(system):
    values = {
        DEVICE: {
            f"ns=1;s=[{DEVICE}]AnalogInput/0": (1.025, "Good", 1700000000123),
            f"ns=1;s=[{DEVICE}]BinaryInput/1": (False, "Good", 0),
        },
        OTHER_DEVICE: {
            f"ns=1;s=[{OTHER_DEVICE}]AnalogInput/0": (
                None,
                "Bad_NotConnected",
                1700000000456,
            ),
            f"ns=1;s=[{OTHER_DEVICE}]AnalogInput/1": (
                -12.5,
                "Bad_Stale",
                1700000000789,
            ),
        },
    }
    qualified = {
        path: qualified_value(*reading)
        for points in values.values()
        for path, reading in points.items()
    }
    elements = {
        device: [
            browse_element(f"[{device}]folder", "FOLDER"),
            browse_element(f"[{device}]object", "OBJECT"),
            browse_element(f"[{device}]method", "METHOD"),
            *(browse_element(path) for path in points),
        ]
        for device, points in values.items()
    }
    system.opc.browse.side_effect = lambda **kwargs: elements[kwargs["device"]]
    system.opc.readValues.side_effect = lambda server, paths: [
        qualified[path] for path in paths
    ]
    return SimpleNamespace(values=values, qualified=qualified, elements=elements)


def assert_error(result, request, status):
    assert set(result) == {"json"}
    assert result["json"]["status"] == "error"
    message = result["json"]["message"]
    assert isinstance(message, str)
    assert message.strip()
    request["servletResponse"].setStatus.assert_called_once_with(status)


def assert_no_write(system):
    assert system.dnp.mock_calls == []
    assert system.opc.mock_calls == []
    assert system.tag.mock_calls == []


def assert_success_status(request):
    assert all(
        status_call == call(200)
        for status_call in request["servletResponse"].setStatus.call_args_list
    )


def assert_sent(result, request, system, body):
    assert set(result) == {"json"}
    payload = result["json"]
    assert payload["status"] == "sent"
    assert payload["pointType"] == body["pointType"]
    assert payload["device"] == body["deviceName"]
    assert payload["index"] == body["index"]
    if body["pointType"] == "analog":
        variation = body.get("variation", 3)
        assert payload["variation"] == variation
        assert payload["value"] == body["value"]
        expected = call.directOperateAnalog(
            body["deviceName"], variation, body["index"], body["value"]
        )
    else:
        params = {**BINARY_DEFAULTS, **body}
        expected = call.directOperateBinary(
            body["deviceName"],
            body["index"],
            params["tcc"],
            params["opType"],
            params["count"],
            params["onTime"],
            params["offTime"],
        )
        for field in BINARY_DEFAULTS:
            if field in payload:
                assert payload[field] == params[field]
    assert system.dnp.mock_calls == [expected]
    system.device.listDevices.assert_called_once_with()
    assert system.opc.mock_calls == []
    assert system.tag.mock_calls == []
    assert_success_status(request)


def assert_get_reads(system, readings, devices):
    system.device.listDevices.assert_called_once_with()
    assert system.opc.browse.call_count == len(devices)
    system.opc.browse.assert_has_calls(
        [call(opcServer=OPC_SERVER, device=device) for device in devices],
        any_order=True,
    )
    paths_read = []
    for read_call in system.opc.readValues.call_args_list:
        server, paths = read_call.args
        assert server == OPC_SERVER
        assert paths
        paths_read.extend(paths)
    assert Counter(paths_read) == Counter(
        path for device in devices for path in readings.values[device]
    )
    assert system.dnp.mock_calls == []
    assert system.tag.mock_calls == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(MISSING, id="absent"),
        pytest.param(None, id="null"),
        pytest.param([], id="empty-list"),
        pytest.param([{"deviceName": DEVICE}], id="list"),
        pytest.param("", id="empty-string"),
        pytest.param('{"deviceName": "rtu-1"}', id="json-string"),
        pytest.param(1, id="integer"),
        pytest.param(True, id="boolean"),
    ],
)
def test_post_rejects_non_dictionary_body(handlers, system, request_factory, body):
    request = request_factory(body=body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("field", ["deviceName", "pointType", "index"])
def test_post_requires_explicit_fields(
    handlers, system, request_factory, post_body, field
):
    del post_body[field]
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


def test_post_rejects_empty_body(handlers, system, request_factory):
    request = request_factory(body={})
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("name", ["", " ", "\t\n", None, True, 1, [], {}])
def test_post_requires_nonblank_device_string(
    handlers, system, request_factory, post_body, name
):
    post_body["deviceName"] = name
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    "point_type",
    ["Analog", "BINARY", "ao", "bo", "AO1", "BO1", "", None, 1, True, [], {}],
)
def test_post_requires_exact_point_type(
    handlers, system, request_factory, post_body, point_type
):
    post_body["pointType"] = point_type
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("index", [-1, 65536, True, False, 1.0, 1.5, "1", None, [], {}])
def test_post_rejects_invalid_index(
    handlers, system, request_factory, post_body, index
):
    post_body["index"] = index
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("index", [0, 1, 65535])
def test_post_dispatches_only_selected_point_type(
    handlers, system, request_factory, post_body, index
):
    post_body["index"] = index
    request = request_factory(body=post_body)
    result = handlers.doPost(request, {})
    assert_sent(result, request, system, post_body)


@pytest.mark.parametrize("name", [DEVICE, OTHER_DEVICE, " literal name "])
def test_post_uses_exact_registered_device_name(
    handlers, system, request_factory, post_body, name
):
    system.device.listDevices.return_value = device_dataset(
        [DEVICE, OTHER_DEVICE, " literal name "]
    )
    post_body["deviceName"] = name
    request = request_factory(body=post_body)
    assert_sent(handlers.doPost(request, {}), request, system, post_body)


@pytest.mark.parametrize(
    "name", ["missing", "RTU-1", "rtu-1 ", " rtu-1", "rtu1", "DNP3", "Connected"]
)
def test_post_unknown_device_never_writes(
    handlers, system, request_factory, post_body, name
):
    post_body["deviceName"] = name
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 404)
    system.device.listDevices.assert_called_once_with()
    assert_no_write(system)


def test_post_empty_device_dataset_never_writes(
    handlers, system, request_factory, post_body
):
    system.device.listDevices.return_value = device_dataset([])
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 404)
    assert_no_write(system)


@pytest.mark.parametrize("field", ["extra", "device", "point", "device_name"])
def test_post_rejects_unknown_fields(
    handlers, system, request_factory, post_body, field
):
    post_body[field] = None
    request = request_factory(body=post_body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    ("point_type", "field", "value"),
    [
        *[("analog", field, value) for field, value in BINARY_DEFAULTS.items()],
        *[("analog", field, None) for field in BINARY_DEFAULTS],
        ("binary", "value", 1.025),
        ("binary", "value", None),
        ("binary", "variation", 3),
        ("binary", "variation", None),
    ],
)
def test_post_rejects_mixed_command_fields(
    handlers, system, request_factory, point_type, field, value
):
    body = {"deviceName": DEVICE, "pointType": point_type, "index": 1}
    if point_type == "analog":
        body["value"] = 2
    body[field] = value
    request = request_factory(body=body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


def test_post_analog_requires_value(handlers, system, request_factory):
    request = request_factory(
        body={"deviceName": DEVICE, "pointType": "analog", "index": 1}
    )
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    ("variation", "value"),
    [
        (MISSING, 0),
        (MISSING, 1.025),
        (1, -(2**31)),
        (1, 2**31 - 1),
        (1, 12.0),
        (1, 0),
        (2, -(2**15)),
        (2, 2**15 - 1),
        (2, -12.0),
        (2, 0),
        (3, 0),
        (3, 1.025),
        (3, -1.025),
        (3, FLOAT32_MAX),
        (3, -FLOAT32_MAX),
        (3, int(FLOAT32_MAX)),
        (3, -int(FLOAT32_MAX)),
        (3, 2.0**-149),
        (3, -(2.0**-149)),
        (4, 0),
        (4, 1.025),
        (4, -1.025),
        (4, FLOAT64_MAX),
        (4, -FLOAT64_MAX),
        pytest.param(4, int(FLOAT64_MAX), id="float64-largest-integer"),
        pytest.param(4, -int(FLOAT64_MAX), id="float64-smallest-integer"),
        (4, 5e-324),
        (4, -5e-324),
    ],
)
def test_post_analog_valid_values_and_variations(
    handlers, system, request_factory, variation, value
):
    body = {"deviceName": DEVICE, "pointType": "analog", "index": 1, "value": value}
    if variation is not MISSING:
        body["variation"] = variation
    request = request_factory(body=body)
    assert_sent(handlers.doPost(request, {}), request, system, body)


@pytest.mark.parametrize(
    "variation", [0, 5, -1, True, False, 3.0, 1.5, "3", None, [], {}]
)
def test_post_analog_rejects_invalid_variation(
    handlers, system, request_factory, variation
):
    request = request_factory(
        body={
            "deviceName": DEVICE,
            "pointType": "analog",
            "index": 1,
            "value": 1,
            "variation": variation,
        }
    )
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("variation", [pytest.param(MISSING, id="default"), 1, 2, 3, 4])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "1.025",
        "",
        None,
        [],
        {},
        float("nan"),
        float("inf"),
        float("-inf"),
        pytest.param(10**1000, id="positive-integer-float-overflow"),
        pytest.param(-(10**1000), id="negative-integer-float-overflow"),
    ],
)
def test_post_analog_rejects_invalid_values_before_writing(
    handlers, system, request_factory, variation, value
):
    body = {"deviceName": DEVICE, "pointType": "analog", "index": 1, "value": value}
    if variation is not MISSING:
        body["variation"] = variation
    request = request_factory(body=body)
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    ("variation", "value"),
    [
        (1, -(2**31) - 1),
        (1, 2**31),
        (1, 1.025),
        (1, -1.025),
        (2, -(2**15) - 1),
        (2, 2**15),
        (2, 1.025),
        (2, -1.025),
        (3, FLOAT32_MAX * 2),
        (3, -FLOAT32_MAX * 2),
        (3, int(FLOAT32_MAX) + 1),
        (3, -int(FLOAT32_MAX) - 1),
        (3, 1e-50),
        (3, -1e-50),
        pytest.param(4, int(FLOAT64_MAX) + 1, id="above-float64-exact-bound"),
        pytest.param(4, -int(FLOAT64_MAX) - 1, id="below-float64-exact-bound"),
    ],
)
def test_post_analog_rejects_out_of_range_or_fractional_integer_values(
    handlers, system, request_factory, variation, value
):
    request = request_factory(
        body={
            "deviceName": DEVICE,
            "pointType": "analog",
            "index": 1,
            "variation": variation,
            "value": value,
        }
    )
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tcc", 0),
        ("tcc", 2),
        ("opType", 0),
        ("opType", 4),
        ("count", 1),
        ("count", 255),
        ("onTime", 0),
        ("onTime", 2147483647),
        ("offTime", 0),
        ("offTime", 2147483647),
    ],
)
def test_post_binary_accepts_each_field_boundary(
    handlers, system, request_factory, field, value
):
    body = {"deviceName": DEVICE, "pointType": "binary", "index": 1, field: value}
    request = request_factory(body=body)
    assert_sent(handlers.doPost(request, {}), request, system, body)


def test_post_binary_passes_all_parameters_in_order(handlers, system, request_factory):
    body = {
        "deviceName": OTHER_DEVICE,
        "pointType": "binary",
        "index": 65535,
        "tcc": 2,
        "opType": 4,
        "count": 255,
        "onTime": 17,
        "offTime": 2147483647,
    }
    request = request_factory(body=body)
    assert_sent(handlers.doPost(request, {}), request, system, body)


@pytest.mark.parametrize("field", list(BINARY_DEFAULTS))
@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, "1", None, [], {}])
def test_post_binary_rejects_noninteger_parameters(
    handlers, system, request_factory, field, value
):
    request = request_factory(
        body={"deviceName": DEVICE, "pointType": "binary", "index": 1, field: value}
    )
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tcc", -1),
        ("tcc", 3),
        ("opType", -1),
        ("opType", 5),
        ("count", 0),
        ("count", 256),
        ("onTime", -1),
        ("onTime", 2147483648),
        ("offTime", -1),
        ("offTime", 2147483648),
    ],
)
def test_post_binary_rejects_out_of_range_parameters(
    handlers, system, request_factory, field, value
):
    request = request_factory(
        body={"deviceName": DEVICE, "pointType": "binary", "index": 1, field: value}
    )
    assert_error(handlers.doPost(request, {}), request, 400)
    assert_no_write(system)


@pytest.mark.parametrize("driver_result", [None, False, {"status": "error"}, object()])
def test_post_reports_sent_without_parsing_driver_result(
    handlers, system, request_factory, post_body, driver_result
):
    system.dnp.directOperateAnalog.return_value = driver_result
    system.dnp.directOperateBinary.return_value = driver_result
    request = request_factory(body=post_body)
    assert_sent(handlers.doPost(request, {}), request, system, post_body)


@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError, OverflowError])
def test_post_driver_exceptions_propagate_without_retry(
    handlers, system, request_factory, post_body, exception_type
):
    error = exception_type("driver failed")
    command = (
        system.dnp.directOperateAnalog
        if post_body["pointType"] == "analog"
        else system.dnp.directOperateBinary
    )
    command.side_effect = error
    request = request_factory(body=post_body)
    with pytest.raises(exception_type, match="driver failed") as caught:
        handlers.doPost(request, {})
    assert caught.value is error
    command.assert_called_once()
    assert len(system.dnp.mock_calls) == 1
    assert system.opc.mock_calls == []
    assert system.tag.mock_calls == []
    request["servletResponse"].setStatus.assert_not_called()


def test_post_device_listing_exception_propagates(
    handlers, system, request_factory, post_body
):
    error = RuntimeError("device listing failed")
    system.device.listDevices.side_effect = error
    request = request_factory(body=post_body)
    with pytest.raises(RuntimeError, match="device listing failed") as caught:
        handlers.doPost(request, {})
    assert caught.value is error
    assert_no_write(system)
    request["servletResponse"].setStatus.assert_not_called()


@pytest.mark.parametrize("details", [MISSING, "false"])
@pytest.mark.parametrize("device", [MISSING, "", DEVICE, OTHER_DEVICE])
def test_get_values_only_preserves_shape_and_device_filter(
    handlers, system, request_factory, readings, details, device
):
    params = {}
    if details is not MISSING:
        params["details"] = details
    if device is not MISSING:
        params["device"] = device
    devices = [DEVICE, OTHER_DEVICE] if device is MISSING or device == "" else [device]
    request = request_factory(params=params)
    assert handlers.doGet(request, {}) == {
        "json": {
            name: {path: reading[0] for path, reading in readings.values[name].items()}
            for name in devices
        }
    }
    assert_get_reads(system, readings, devices)
    for qualified in readings.qualified.values():
        qualified.getQuality.assert_not_called()
        qualified.getTimestamp.assert_not_called()
    assert_success_status(request)


@pytest.mark.parametrize("device", [MISSING, "", DEVICE, OTHER_DEVICE])
def test_get_details_preserves_keys_quality_null_and_epoch_milliseconds(
    handlers, system, request_factory, readings, device
):
    params = {"details": "true"}
    if device is not MISSING:
        params["device"] = device
    devices = [DEVICE, OTHER_DEVICE] if device is MISSING or device == "" else [device]
    request = request_factory(params=params)
    assert handlers.doGet(request, {}) == {
        "json": {
            name: {
                path: {"value": value, "quality": quality, "timestamp": timestamp}
                for path, (value, quality, timestamp) in readings.values[name].items()
            }
            for name in devices
        }
    }
    assert_get_reads(system, readings, devices)
    assert_success_status(request)


@pytest.mark.parametrize(
    "details",
    ["", "True", "FALSE", "yes", "1", "0", " true ", None, True, False, 1, 0, [], {}],
)
def test_get_rejects_invalid_details_before_backend_operations(
    handlers, system, request_factory, details
):
    request = request_factory(params={"details": details})
    assert_error(handlers.doGet(request, {}), request, 400)
    assert system.device.mock_calls == []
    assert_no_write(system)


@pytest.mark.parametrize("details", ["false", "true"])
@pytest.mark.parametrize(
    "device", ["missing", " ", "RTU-1", "rtu-1 ", " rtu-1", "DNP3", "Connected"]
)
def test_get_unknown_device_returns_404_without_browse_or_read(
    handlers, system, request_factory, details, device
):
    request = request_factory(params={"device": device, "details": details})
    assert_error(handlers.doGet(request, {}), request, 404)
    system.device.listDevices.assert_called_once_with()
    assert_no_write(system)


@pytest.mark.parametrize("details", ["false", "true"])
@pytest.mark.parametrize("device", [MISSING, ""])
def test_get_empty_device_dataset(handlers, system, request_factory, details, device):
    system.device.listDevices.return_value = device_dataset([])
    params = {"details": details}
    if device is not MISSING:
        params["device"] = device
    request = request_factory(params=params)
    assert handlers.doGet(request, {}) == {"json": {}}
    system.device.listDevices.assert_called_once_with()
    assert_no_write(system)
    assert_success_status(request)


def test_get_unknown_device_in_empty_dataset(handlers, system, request_factory):
    system.device.listDevices.return_value = device_dataset([])
    request = request_factory(params={"device": DEVICE})
    assert_error(handlers.doGet(request, {}), request, 404)
    assert_no_write(system)


@pytest.mark.parametrize("details", ["false", "true"])
@pytest.mark.parametrize("element_types", [[], ["FOLDER"], ["OBJECT", "METHOD"]])
def test_get_no_data_variables_keeps_empty_devices_without_reading(
    handlers, system, request_factory, details, element_types
):
    system.opc.browse.return_value = [
        browse_element(f"ignored/{kind}", kind) for kind in element_types
    ]
    request = request_factory(params={"details": details})
    assert handlers.doGet(request, {}) == {"json": {DEVICE: {}, OTHER_DEVICE: {}}}
    system.device.listDevices.assert_called_once_with()
    system.opc.browse.assert_has_calls(
        [
            call(opcServer=OPC_SERVER, device=DEVICE),
            call(opcServer=OPC_SERVER, device=OTHER_DEVICE),
        ],
        any_order=True,
    )
    assert system.opc.browse.call_count == 2
    system.opc.readValues.assert_not_called()
    assert system.tag.mock_calls == []
    assert system.dnp.mock_calls == []
    assert_success_status(request)


def test_get_empty_device_does_not_hide_other_devices(
    handlers, system, request_factory, readings
):
    readings.values[DEVICE] = {}
    readings.elements[DEVICE] = [browse_element("folder", "FOLDER")]
    request = request_factory()
    assert handlers.doGet(request, {}) == {
        "json": {
            DEVICE: {},
            OTHER_DEVICE: {
                path: reading[0]
                for path, reading in readings.values[OTHER_DEVICE].items()
            },
        }
    }
    assert_get_reads(system, readings, [DEVICE, OTHER_DEVICE])
    system.opc.readValues.assert_called_once()
    assert_success_status(request)


@pytest.mark.parametrize("details", ["false", "true"])
@pytest.mark.parametrize("operation", ["listDevices", "browse", "readValues"])
def test_get_backend_exceptions_propagate(
    handlers, system, request_factory, readings, details, operation
):
    error = RuntimeError(f"{operation} failed")
    backend = system.device if operation == "listDevices" else system.opc
    getattr(backend, operation).side_effect = error
    request = request_factory(params={"device": DEVICE, "details": details})
    with pytest.raises(RuntimeError, match=f"{operation} failed") as caught:
        handlers.doGet(request, {})
    assert caught.value is error
    getattr(backend, operation).assert_called_once()
    if operation == "listDevices":
        assert system.opc.mock_calls == []
    elif operation == "browse":
        system.opc.readValues.assert_not_called()
    assert system.tag.mock_calls == []
    assert system.dnp.mock_calls == []
    request["servletResponse"].setStatus.assert_not_called()


@pytest.mark.parametrize(
    ("details", "accessor"),
    [
        ("false", "getValue"),
        ("true", "getValue"),
        ("true", "getQuality"),
        ("true", "getTimestamp"),
        ("true", "getTime"),
    ],
)
def test_get_qualified_value_exceptions_propagate(
    handlers, system, request_factory, readings, details, accessor
):
    qualified = readings.qualified[next(iter(readings.values[DEVICE]))]
    error = RuntimeError(f"{accessor} failed")
    target = (
        qualified.getTimestamp.return_value.getTime
        if accessor == "getTime"
        else getattr(qualified, accessor)
    )
    target.side_effect = error
    request = request_factory(params={"device": DEVICE, "details": details})
    with pytest.raises(RuntimeError, match=f"{accessor} failed") as caught:
        handlers.doGet(request, {})
    assert caught.value is error
    target.assert_called_once()
    assert system.tag.mock_calls == []
    assert system.dnp.mock_calls == []
    request["servletResponse"].setStatus.assert_not_called()
