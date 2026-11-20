from pathlib import Path

import pytest

from phenix_apps.common import mmcapture
from phenix_apps.common.error import AppError


class VersionMM:
    def __init__(self, *answers):
        self.answers = answers

    def version(self):
        return [{"Response": a} for a in self.answers]


@pytest.mark.parametrize(
    ("answer", "version"),
    [
        ("minimega 3.4.0 abc 2026-12-01", (3, 4, 0)),
        ("minimega v3.4.0-rc1 abc 2026-12-01", (3, 4, 0)),
        ("minimega 3.10.2 abc 2027-01-01", (3, 10, 2)),
        ("minimega 3.3.0", (3, 3, 0)),
        ("minimega", None),
        ("minimega dev abc", None),
        ("", None),
    ],
)
def test_parse_version(answer, version):
    assert mmcapture.parse_version(answer) == version


@pytest.mark.parametrize(
    ("answers", "available"),
    [
        (["minimega 3.4.0 a b"], True),
        (["minimega 3.4.0-rc1 a b"], True),
        (["minimega 3.5.1 a b", "minimega 3.4.0 a b"], True),
        (["minimega 3.3.0 a b"], False),
        (["minimega 3.4.0 a b", "minimega 3.3.0 a b"], False),
        (["minimega 3.4.0 a b", "unknown"], False),
        ([], False),
    ],
)
def test_capture_support_follows_the_oldest_node(answers, available):
    assert mmcapture.capture_support(VersionMM(*answers)).available is available


def test_capture_support_names_the_oldest_version_and_the_minimum():
    support = mmcapture.capture_support(
        VersionMM("minimega 3.4.0 a b", "minimega 3.3.0 a b")
    )

    assert support.version == "3.3.0"
    assert support.reason == (
        "requires minimega 3.4.0 or later; the oldest node runs 3.3.0"
    )


def test_capture_support_ignores_a_node_that_answers_with_an_error():
    class ErrorMM:
        def version(self):
            return [
                {"Response": "minimega 3.4.0 a b"},
                {"Response": "", "Error": "node down"},
            ]

    assert mmcapture.capture_support(ErrorMM()).available is True


def test_require_raises_with_the_reason():
    support = mmcapture.capture_support(VersionMM("minimega 3.3.0 a b"))

    with pytest.raises(RuntimeError, match=r"format: pcapng requires minimega 3\.4\.0"):
        support.require("format: pcapng")
    mmcapture.capture_support(VersionMM("minimega 3.4.0 a b")).require("anything")


def test_capture_options_builds_one_string_in_a_fixed_order():
    options = mmcapture.capture_options(
        filter="tcp port 80",
        snaplen=128,
        format="pcapng",
        vlans=["EXP_1", "EXP_2"],
        vms=["aa", "bb"],
        bridges=["phenix"],
    )

    assert options == (
        "format=pcapng vlans=EXP_1,EXP_2 bridges=phenix vms=aa,bb "
        "filter='tcp port 80' snaplen=128"
    )


def test_capture_options_is_none_when_nothing_is_set():
    assert mmcapture.capture_options() is None
    assert mmcapture.capture_options(snaplen=0, filter="") is None


@pytest.mark.parametrize("snaplen", [1, 13, 65536, -5])
def test_capture_options_refuses_a_snaplen_minimega_would_refuse(snaplen):
    with pytest.raises(ValueError, match="14 to 65535"):
        mmcapture.capture_options(snaplen=snaplen)


@pytest.mark.parametrize("snaplen", [14, 1600, 65535])
def test_capture_options_accepts_the_snaplen_range(snaplen):
    assert mmcapture.capture_options(snaplen=snaplen) == f"snaplen={snaplen}"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filter": "it's"},
        {"filter": "a#b"},
        {"vlans": ["a b"]},
        {"vms": ["a b", "c"]},
        {"bridges": ["a'b"]},
        {"format": "pcapng filter=x"},
    ],
)
def test_capture_options_refuses_text_minimega_would_misread(kwargs):
    with pytest.raises(AppError):
        mmcapture.capture_options(**kwargs)


def test_capture_options_refuses_a_comma_inside_a_name():
    with pytest.raises(AppError, match="invalid vlan 'a,b'"):
        mmcapture.capture_options(vlans=["a,b"])


def test_rows_use_the_header_not_the_position():
    resp = [
        {"Header": ["state", "id", "path"], "Tabular": [["running", "3", "/f.pcap"]]},
        {"Header": ["path", "extra", "id"], "Tabular": [["/g.pcap", "x", "4"]]},
        {"Header": ["id"], "Tabular": [["5", "dropped"]]},
        {"Tabular": [["no", "header"]]},
        "not a response",
    ]

    assert mmcapture.rows(resp) == [
        {"state": "running", "id": "3", "path": "/f.pcap"},
        {"path": "/g.pcap", "extra": "x", "id": "4"},
        {"id": "5"},
        {},
    ]
    assert mmcapture.rows(None) == []


def test_path_helpers():
    row = {"path": "/files/run/a.pcap"}

    assert mmcapture.path_of(row) == Path("/files/run/a.pcap")
    assert mmcapture.path_of({"path": ""}) is None
    assert mmcapture.is_under(row, Path("/files/run"))
    assert not mmcapture.is_under(row, Path("/files/run2"))
    assert not mmcapture.is_under({}, Path("/files"))


def test_summarize_keeps_state_and_counters_as_numbers():
    row = {"state": "stopped", "packets": "12", "kdrops": "", "path": "/f"}

    assert mmcapture.summarize(row) == {
        "minimega_state": "stopped",
        "minimega_packets": 12,
    }


def test_check_final_raises_with_minimegas_error():
    rows = [
        {"state": "stopped", "path": "/a.pcap"},
        {"state": "failed", "error": "disk full", "path": "/b.pcap"},
        {"state": "orphaned", "path": "/c.pcap"},
    ]

    with pytest.raises(RuntimeError) as err:
        mmcapture.check_final(rows)

    assert "/b.pcap: failed: disk full" in str(err.value)
    assert "/c.pcap: orphaned: no error given" in str(err.value)
    assert "/a.pcap" not in str(err.value)


def test_check_final_accepts_old_rows_with_no_state():
    mmcapture.check_final([{"path": "/a.pcap"}])


@pytest.mark.parametrize(
    ("out", "count"),
    [("[]", 0), ("[a]", 1), ("[a, b]", 2), (" [a,b,c] \n", 3)],
)
def test_count_mirrors(out, count):
    assert mmcapture.count_mirrors(out) == count


@pytest.mark.parametrize("out", ["", "no bridge named x", "a, b"])
def test_count_mirrors_refuses_other_text(out):
    with pytest.raises(ValueError, match="cannot read the Open vSwitch mirror list"):
        mmcapture.count_mirrors(out)


def test_namespace_vlans():
    status = {"MGMT": 1, "mgmt2": 2, "EXP_2": 102, "EXP_1": 101}

    assert mmcapture.namespace_vlans(None, status) == ["EXP_1", "EXP_2", "mgmt2"]
    assert mmcapture.namespace_vlans(["MGMT"], status) == ["MGMT"]
    with pytest.raises(ValueError, match="no VLAN besides MGMT"):
        mmcapture.namespace_vlans(None, {"mgmt": 1})
    with pytest.raises(ValueError, match="no VLAN besides MGMT"):
        mmcapture.namespace_vlans(None, None)
