import json
import threading
import time
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.hoststats.hoststats import HostStats, HostStatsMetadata
from phenix_apps.testing.readme import readme_yaml

README = Path(__file__).parents[1] / "README.md"


def test_readme_example_runs_in_the_background():
    (app,) = readme_yaml(README, "Example")
    (cmp,) = app["components"]

    assert cmp["background"] is True
    assert cmp["name"] in app["runs"][0]["start"]
    assert cmp["name"] in app["runs"][0]["stop"]
    _, warnings = validate_metadata(HostStatsMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_unknown_key_warns_but_filebeat_inputs_does_not():
    _, warnings = validate_metadata(
        HostStatsMetadata, {"filebeat.inputs": [{}], "pollPeriods": 5}, "h"
    )
    assert len(warnings) == 1
    assert "did you mean 'pollPeriod'" in warnings[0]


def test_filebeat_inputs_must_be_a_list():
    with pytest.raises(ValueError, match=r"filebeat\.inputs"):
        parse_metadata(HostStatsMetadata, {"filebeat.inputs": "x"}, "h")


@pytest.mark.parametrize("bad", [False, 0, "", []])
def test_falsy_non_mapping_metadata_is_rejected_not_defaulted(bad):
    with pytest.raises(ValueError, match="invalid metadata"):
        parse_metadata(HostStatsMetadata, bad, "h")


@pytest.mark.parametrize(
    ("md", "poll", "every"),
    [
        ({}, 5.0, 1),
        ({"pollPeriod": 2, "flushPeriod": 7}, 2.0, 3),  # rounded down
        ({"flushPeriod": 0}, 5.0, 1),  # below pollPeriod: every sample
        ({"flushPeriod": -1}, 5.0, 1),
        ({"pollPeriod": 0.5}, 0.5, 1),
    ],
)
def test_periods_match_the_old_arithmetic(md, poll, every):
    config = parse_metadata(HostStatsMetadata, md, "h")
    assert (config.pollPeriod, config.flush_every) == (poll, every)


@pytest.mark.parametrize("bad", [0, -5, "fast", float("inf")])
def test_bad_poll_period_is_rejected(bad):
    with pytest.raises(ValueError, match="pollPeriod"):
        parse_metadata(HostStatsMetadata, {"pollPeriod": bad}, "h")


class FakeMinimega:
    def __init__(self, fail_first: bool = False):
        self.fail_first = fail_first
        self.calls = 0

    def vm_info(self):
        return [
            {
                "Host": "node1",
                "Header": ["id", "name"],
                "Tabular": [["1", "b"], ["2", "a"]],
            }
        ]

    def host(self):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("minimega busy")
        return [{"Data": {"Name": "node1", "Load": "0.5 0.25 0.1", "CPUs": 8}}]


def component(tmp_path, mm, poll: float) -> HostStats:
    hs = HostStats.__new__(HostStats)
    hs.config = HostStatsMetadata.model_validate({"pollPeriod": poll})
    hs.base_dir = tmp_path
    hs.resdata = []
    hs.stopped = threading.Event()
    hs.mm = mm
    return hs


def test_samples_are_written_and_a_failed_poll_is_retried(tmp_path):
    hs = component(tmp_path, FakeMinimega(fail_first=True), poll=0.01)
    thread = threading.Thread(target=hs._HostStats__run_monitor)
    thread.start()
    time.sleep(0.2)
    hs.stopped.set()
    thread.join()

    lines = (tmp_path / "host_stats.jsonl").read_text().splitlines()
    record = json.loads(lines[0])
    assert record["compute_name"] == "node1"
    assert (record["Load_1"], record["Load_5"], record["Load_15"]) == (0.5, 0.25, 0.1)
    assert record["vm_list"] == ["a", "b"]
    assert record["CPUs"] == 8


def test_stop_wakes_a_long_poll_immediately(tmp_path):
    hs = component(tmp_path, FakeMinimega(), poll=60)
    thread = threading.Thread(target=hs._HostStats__run_monitor)
    thread.start()
    time.sleep(0.1)

    began = time.monotonic()
    hs.stopped.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert time.monotonic() - began < 2  # phenix kills it 10 s after SIGTERM


def test_each_sample_logs_a_one_line_summary(tmp_path):
    from phenix_apps.common.logger import logger

    lines = []
    sink = logger.add(lambda msg: lines.append(msg.record["message"]), level="INFO")
    try:
        component(tmp_path, FakeMinimega(), poll=1)._HostStats__get_resdata()
    finally:
        logger.remove(sink)

    assert "node1: load 0.5, 2 VMs" in lines
    assert not any("vm_list" in line for line in lines)
