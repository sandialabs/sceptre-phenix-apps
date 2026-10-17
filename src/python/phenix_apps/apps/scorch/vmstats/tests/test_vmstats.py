import json
import shutil
import subprocess
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.vmstats.vmstats import (
    VMStats,
    VMStatsMetadata,
    parse_vmstat,
    vmstat_script,
)
from phenix_apps.testing.readme import readme_components, readme_yaml

README = Path(__file__).parents[1] / "README.md"

HEADER = (
    "procs -----------memory---------- ---swap-- -----io---- -system-- "
    "------cpu----- -----timestamp-----\n"
    " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs "
    "us sy id wa st                 UTC\n"
)
SAMPLE = (
    " 1  0      0 812345  20480 409600    0    0     3     7  112  230  "
    "2  1 97  0  0 2026-10-13 12:00:01\n"
)


def test_readme_example_is_valid_and_listed_in_start_and_stop():
    (cmp,) = readme_components(README, "vmstats")
    (doc,) = readme_yaml(README)

    _, warnings = validate_metadata(VMStatsMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []
    assert cmp["name"] in doc["runs"][0]["start"]
    assert cmp["name"] in doc["runs"][0]["stop"]


@pytest.mark.parametrize(
    ("md", "poll", "vms"),
    [
        ({}, 1, None),
        ({"pollPeriod": 5}, 5, None),
        ({"vms": None}, 1, None),
        ({"vms": ["load[1-3]", "attacker"]}, 1, ["load[1-3]", "attacker"]),
    ],
)
def test_valid_forms(md, poll, vms):
    config = parse_metadata(VMStatsMetadata, md, "v")
    assert (config.pollPeriod, config.vms) == (poll, vms)


@pytest.mark.parametrize(
    "md",
    [
        {"pollPeriod": 0},
        {"pollPeriod": 0.5},
        {"pollPeriod": "1; reboot"},
        {"vms": ["load 5"]},
        {"vms": "load5"},
        {"vms": []},
        {"stopWait": -1},
        {"vms": ["../x"]},
        {"vms": ["load1#suffix"]},
        {"vms": ["load\\1"]},
    ],
)
def test_bad_metadata_is_rejected(md):
    with pytest.raises(ValueError, match="invalid metadata"):
        parse_metadata(VMStatsMetadata, md, "v")


def test_parse_vmstat_reads_samples():
    stats, skipped = parse_vmstat(HEADER + SAMPLE, "load5")

    assert skipped == 0
    assert stats == [
        {
            "r": 1,
            "b": 0,
            "swpd": 0,
            "free": 812345,
            "buff": 20480,
            "cache": 409600,
            "si": 0,
            "so": 0,
            "bi": 3,
            "bo": 7,
            "in": 112,
            "cs": 230,
            "us": 2,
            "sy": 1,
            "id": 97,
            "wa": 0,
            "st": 0,
            "UTC": "2026-10-13 12:00:01",
            "vm_name": "load5",
        }
    ]


def test_parse_vmstat_survives_a_rerun_and_a_cut_line():
    # miniccc reran vmstat after a reconnect (second header), and the last
    # line was cut short when vmstat was killed
    text = HEADER + SAMPLE + HEADER + SAMPLE + " 0  0      0 81"
    stats, skipped = parse_vmstat(text, "a")

    assert len(stats) == 2
    assert skipped == 1


@pytest.mark.parametrize(
    "cut", ["2026-10-13 12:00:", "2026-10-13 12:00:0", "2026-10-1"]
)
def test_parse_vmstat_skips_a_sample_cut_inside_its_timestamp(cut):
    line = SAMPLE.rsplit(" 2026", 1)[0] + " " + cut
    stats, skipped = parse_vmstat(HEADER + SAMPLE + line, "a")

    assert len(stats) == 1
    assert skipped == 1


def test_parse_vmstat_names_the_time_column_after_the_timezone():
    stats, _ = parse_vmstat(HEADER.replace(" UTC", " EST") + SAMPLE, "a")
    assert stats[0]["EST"] == "2026-10-13 12:00:01"


class FakeMinimega:
    def __getattr__(self, name):
        return lambda *args: None


@pytest.mark.parametrize(
    "error",
    [
        ValueError("['/vmstat.out'] not found in VM broken"),
        RuntimeError("timed out waiting for miniccc client on broken"),
    ],
)
def test_stop_keeps_the_others_when_one_vm_has_no_output(tmp_path, monkeypatch, error):
    def recv(mm, vm, src, dst):
        if vm == "broken":
            raise error
        Path(dst).write_text(HEADER + SAMPLE)

    monkeypatch.setattr("phenix_apps.common.utils.mm_recv", recv)
    monkeypatch.setattr(
        "phenix_apps.apps.scorch.vmstats.vmstats.time.sleep", lambda s: None
    )

    component = VMStats.__new__(VMStats)
    component.name = "vmstats"
    component.base_dir = tmp_path
    component.mm = FakeMinimega()
    component.config = parse_metadata(
        VMStatsMetadata, {"vms": ["a", "broken", "b"]}, "v"
    )

    with pytest.raises(RuntimeError, match=r"no vmstat.out from 1 VM\(s\).*: broken"):
        component.stop()

    records = [
        json.loads(x) for x in (tmp_path / "vm_stats.jsonl").read_text().splitlines()
    ]
    assert [r["vm_name"] for r in records] == ["a", "b"]


OLD_VMSTAT = """#!/bin/sh
# procps before 3.3: no -t
case " $* " in *" -t "*) echo "vmstat: invalid option -- 't'" >&2; exit 2;; esac
echo "procs -----------memory---------- ---swap-- -----io---- -system-- ----cpu----"
echo " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa"
echo " 1  0      0 812345  12345 234567    0    0     1     2   30   40  1  2 97  0"
"""


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_vmstat_script_stamps_samples_when_vmstat_lacks_t(tmp_path):
    fake = tmp_path / "vmstat"
    fake.write_text(OLD_VMSTAT)
    fake.chmod(0o755)
    script = vmstat_script(1)
    assert "'" not in script  # wrapped in bash -c '...'

    out = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    stats, skipped = parse_vmstat(out, "router")

    assert skipped == 0
    assert len(stats) == 1
    assert stats[0]["r"] == 1
    assert stats[0]["free"] == 812345
    assert stats[0]["vm_name"] == "router"
    assert len(stats[0]["UTC"]) == len("2026-10-18 12:00:00")


def test_default_vm_list_includes_vyos_and_skips_windows():
    os_types = {
        "a": "linux",
        "r": "vyos",
        "v": "vyatta",
        "w": "windows",
        "m": "minirouter",
    }
    component = VMStats.__new__(VMStats)
    component.config = parse_metadata(VMStatsMetadata, {}, "v")
    component.extract_node_names = lambda: list(os_types)
    component.extract_node = lambda n: {"hardware": {"os_type": os_types[n]}}

    assert component._VMStats__vm_list() == ["a", "r", "v"]
