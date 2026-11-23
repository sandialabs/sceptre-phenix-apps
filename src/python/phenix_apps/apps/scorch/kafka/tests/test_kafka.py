import csv
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.kafka import kafka_listener as listener
from phenix_apps.apps.scorch.kafka.kafka_component import Kafka, KafkaMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"

SENSORS = [
    {"name": "exp.sensors.a", "filter": [{"key": "name", "value": "bus*"}]},
    {"name": "exp.sensors.b", "filter": [{"key": "state", "value": "on"}]},
]


class Done(Exception):
    """Ends the listener's endless loop once the fake consumer has no more."""


class FakeConsumer:
    """Yields (topic, raw bytes) through the deserializer the listener gave it,
    the way KafkaConsumer does, then ends the run."""

    def __init__(self, messages, **kwargs):
        self.messages = messages
        self.deserialize = kwargs["value_deserializer"]
        self.served = False

    def subscribe(self, topics=None, pattern=None):
        self.subscribed = topics or pattern

    def topics(self):
        return {t for t, _ in self.messages}

    def __iter__(self):
        if self.served:
            raise Done
        self.served = True
        for topic, raw in self.messages:
            yield SimpleNamespace(topic=topic, value=self.deserialize(raw))


def listen(monkeypatch, tmp_path, messages, topics, csv_out=False, wait="0"):
    """Run the listener over `messages` and return what it wrote."""
    monkeypatch.setattr(
        listener, "KafkaConsumer", lambda **kw: FakeConsumer(messages, **kw)
    )
    out = tmp_path / ("out.csv" if csv_out else "out.ndjson")
    with pytest.raises(Done):
        listener.run(csv_out, str(out), "k:9092", json.dumps(topics), "exp", wait)
    if csv_out:
        with out.open(newline="") as f:
            return list(csv.DictReader(f))
    return [json.loads(line) for line in out.read_text().splitlines()]


def raw(data):
    return json.dumps(data).encode()


# --- each topic's filter applies to that topic only ---


@pytest.mark.parametrize(
    ("name", "topic", "matches"),
    [
        ("exp.a", "exp.a", True),
        ("exp.a", "exp.ab", False),
        ("exp.a*", "exp.ab", True),
        ("exp.a*", "exp.a", True),
        ("exp.a*", "other.exp.ab", False),  # right wildcards only
        ("*", "anything", True),
    ],
)
def test_topic_names_match_exactly_or_by_a_right_wildcard(name, topic, matches):
    assert listener.topic_matches(name, topic) is matches


def test_a_topic_filter_applies_only_to_its_own_topic(monkeypatch, tmp_path):
    rows = listen(
        monkeypatch,
        tmp_path,
        [
            ("exp.sensors.a", raw({"name": "bus1", "state": "off"})),
            # b's filter (state=on) matches this, but it is on a, whose filter does not
            ("exp.sensors.a", raw({"name": "dev1", "state": "on"})),
            ("exp.sensors.b", raw({"name": "bus2", "state": "off"})),
            ("exp.sensors.b", raw({"name": "dev2", "state": "on"})),
        ],
        SENSORS,
    )
    assert [r["name"] for r in rows] == ["bus1", "dev2"]


def test_an_unfiltered_topic_keeps_only_its_own_messages(monkeypatch, tmp_path):
    topics = [{"name": "exp.all"}, SENSORS[0]]
    rows = listen(
        monkeypatch,
        tmp_path,
        [
            ("exp.all", raw({"name": "x"})),
            ("exp.sensors.a", raw({"name": "dev1"})),
        ],
        topics,
    )
    assert rows == [{"topic": "exp.all", "name": "x"}]


def test_a_topics_filters_are_alternatives_and_a_row_is_written_once(
    monkeypatch, tmp_path
):
    topics = [
        {
            "name": "exp.t",
            "filter": [{"key": "name", "value": "bus*"}, {"key": "on", "value": True}],
        }
    ]
    rows = listen(
        monkeypatch,
        tmp_path,
        [
            ("exp.t", raw({"name": "bus1", "on": True})),
            ("exp.t", raw({"name": "dev1", "on": True})),
            ("exp.t", raw({"name": "dev2", "on": False})),
        ],
        topics,
    )
    assert [r["name"] for r in rows] == ["bus1", "dev1"]


def test_no_topics_keeps_every_message(monkeypatch, tmp_path):
    rows = listen(monkeypatch, tmp_path, [("exp.x", raw({"a": 1}))], [])
    assert rows == [{"topic": "exp.x", "a": 1}]


def test_a_wildcard_subscribes_by_prefix(monkeypatch, tmp_path):
    made = []

    def consumer(**kw):
        made.append(FakeConsumer([("exp.a1", b"{}"), ("x.exp.a2", b"{}")], **kw))
        return made[0]

    monkeypatch.setattr(listener, "KafkaConsumer", consumer)
    with pytest.raises(Done):
        listener.run(
            False,
            str(tmp_path / "o"),
            "k:1",
            json.dumps([{"name": "exp.a*"}]),
            "e",
            "5",
        )
    assert made[0].subscribed == ["exp.a1"]


def test_a_wildcard_overlapping_a_named_topic_does_not_wait(monkeypatch, tmp_path):
    def no_sleep(_):
        raise AssertionError("waited for topics that were already there")

    monkeypatch.setattr(listener.time, "sleep", no_sleep)
    topics = [{"name": "exp.foo.bar2"}, {"name": "exp.foo.bar*"}]
    rows = listen(
        monkeypatch, tmp_path, [("exp.foo.bar2", raw({"a": 1}))], topics, wait="5"
    )
    assert rows == [{"topic": "exp.foo.bar2", "a": 1}]


# --- the CSV header grows with the keys ---


def test_csv_keeps_keys_that_first_appear_in_later_messages(monkeypatch, tmp_path):
    rows = listen(
        monkeypatch,
        tmp_path,
        [("exp.cols", raw({"x": 1, "y1": 2})), ("exp.cols", raw({"x": 3, "y2": 4}))],
        [],
        csv_out=True,
    )
    assert rows == [
        {"topic": "exp.cols", "x": "1", "y1": "2", "y2": ""},
        {"topic": "exp.cols", "x": "3", "y1": "", "y2": "4"},
    ]


def test_csv_appends_to_an_existing_file_under_one_header(tmp_path):
    path = tmp_path / "out.csv"
    path.write_text("topic,x\r\nexp.t,1\r\n")
    sink = listener.CsvSink(path)
    sink.write({"topic": "exp.t", "x": 2})
    sink.write({"topic": "exp.t", "x": 3, "z": 9})
    lines = path.read_text().splitlines()
    assert lines == ["topic,x,z", "exp.t,1,", "exp.t,2,", "exp.t,3,9"]


def test_csv_widens_past_a_value_longer_than_the_default_field_limit(tmp_path):
    path = tmp_path / "out.csv"
    big = "v" * 140_000
    sink = listener.CsvSink(path)
    sink.write({"topic": "exp.t", "x": big})
    sink.write({"topic": "exp.t", "x": 1, "z": 2})
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"topic": "exp.t", "x": big, "z": ""},
        {"topic": "exp.t", "x": "1", "z": "2"},
    ]


# --- a bad message is skipped, not fatal ---


@pytest.mark.parametrize(
    "bad", [b"not json", b"\xff\xfe", b"5", b"[1, 2]", b"null", None]
)
def test_a_message_that_is_not_a_json_object_is_skipped(bad, capsys):
    assert listener.decode(bad) is None
    assert "skipping" in capsys.readouterr().err


def test_the_listener_keeps_going_after_a_bad_message(monkeypatch, tmp_path):
    messages = [("exp.raw", b"not json 1"), ("exp.raw", raw({"name": "ok"}))]
    for csv_out in (False, True):
        rows = listen(monkeypatch, tmp_path, messages, [], csv_out=csv_out)
        assert [r["name"] for r in rows] == ["ok"]


# --- configure: ports, the listener's log, the metadata model ---


def component(tmp_path, **md):
    comp = object.__new__(Kafka)
    comp.name, comp.exp_name, comp.component_id = "kafka", "exp", "c0ffee"
    comp.base_dir = tmp_path / "out"
    comp.pid_file = tmp_path / "kafka.pid"
    comp.metadata = md
    comp.config = parse_metadata(KafkaMetadata, md, "kafka")
    return comp


@pytest.fixture
def popen(monkeypatch):
    calls = []

    def fake(command, **kw):
        calls.append((command, kw))
        return SimpleNamespace(pid=4242, poll=lambda: None)

    monkeypatch.setattr(subprocess, "Popen", fake)
    return calls


def test_an_endpoint_port_is_an_integer(tmp_path, popen):
    comp = component(tmp_path, kafka_endpoints=[{"ip": "10.0.0.5", "port": 19092}])
    comp.configure()
    ((command, _),) = popen
    assert "10.0.0.5:19092" in command
    assert comp.pid_file.read_text() == "4242"


def test_an_ipv6_broker_is_bracketed(tmp_path, popen):
    component(tmp_path, kafka_endpoints=[{"ip": "::1", "port": 9092}]).configure()
    ((command, _),) = popen
    assert "[::1]:9092" in command


def test_csv_false_writes_ndjson(tmp_path, popen):
    comp = component(tmp_path, csv=False)
    comp.configure()
    ((command, _),) = popen
    assert command[2] == "False"
    assert comp.path.name == "kafka_output.ndjson"


def test_endpoints_default_to_the_local_broker(tmp_path, popen):
    component(tmp_path).configure()
    ((command, _),) = popen
    assert "127.0.0.1:9092" in command


def test_the_listener_logs_to_a_file_beside_its_output(tmp_path, popen):
    comp = component(tmp_path)
    comp.configure()
    ((_, kw),) = popen
    assert kw["stderr"].name == str(tmp_path / "out" / "kafka_listener.log")
    assert kw["stdout"] is kw["stderr"]
    assert kw["stderr"].closed  # the parent's copy; the listener has its own


def test_configure_passes_the_topics_to_the_listener(tmp_path, popen):
    component(tmp_path, topics=SENSORS, csv=False).configure()
    ((command, _),) = popen
    assert json.loads(command[5]) == SENSORS
    assert command[1].endswith("kafka_listener.py")
    assert command[2] == "False"


@pytest.mark.parametrize(
    "md",
    [
        {},
        {"kafka_endpoints": [{"ip": "1.0.0.0", "port": 9092}]},
        {"kafka_endpoints": [{"ip": "::1", "port": 9092}], "csv": False},
        {"wait_duration_seconds": 700},
        {"topics": [{"name": "exp.t"}, {"name": "exp.u", "filter": None}]},
        {"topics": [{"name": "exp.t", "filter": [{"key": "on", "value": False}]}]},
        {"csv": False, "topics": None},
    ],
)
def test_the_model_accepts_the_configs_that_already_work(md):
    _, warnings = validate_metadata(KafkaMetadata, md, "kafka")
    assert warnings == []


@pytest.mark.parametrize(
    ("md", "problem"),
    [
        ({"kafka_endpoints": [{"ip": "1.0.0.0", "port": "nine"}]}, "port"),
        ({"kafka_endpoints": [{"port": 9092}]}, "ip"),
        ({"kafka_endpoints": [{"ip": "1.0.0.0", "port": 70000}]}, "port"),
        ({"topics": [{"filter": []}]}, "name"),
        ({"topics": [{"name": "t", "filter": [{"value": 1}]}]}, "key"),
        ({"kafka_endpoints": [{"ip": "1.0.0.0", "port": "9092"}]}, "port"),
        ({"kafka_endpoints": [{"ip": "broker", "port": 9092}]}, "ip"),
        ({"kafka_endpoints": [{"ip": "1.0.0", "port": 9092}]}, "ip"),
        ({"kafka_endpoints": [{"ip": "1.0.0.0", "port": True}]}, "port"),
        ({"wait_duration_seconds": "305"}, "wait_duration_seconds"),
        ({"csv": "false"}, "csv"),
        ({"csv": "maybe"}, "csv"),
        ({"wait_duration_seconds": -1}, "wait_duration_seconds"),
        ({"topics": [{"name": ""}]}, "name"),
    ],
)
def test_the_model_rejects_configs_that_crash_or_hang(md, problem):
    with pytest.raises(ValueError, match=problem):
        parse_metadata(KafkaMetadata, md, "kafka")


def test_readme_has_examples():
    assert len(readme_components(README, "kafka")) == 2


@pytest.mark.parametrize(
    "cmp", readme_components(README, "kafka"), ids=lambda c: c["name"]
)
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(KafkaMetadata, cmp.get("metadata"), cmp["name"])
    assert warnings == []
