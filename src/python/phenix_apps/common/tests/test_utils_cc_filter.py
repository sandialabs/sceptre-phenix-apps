import pytest

from phenix_apps.common import utils


class _RecordingMM:
    """Records cc_filter, cc_exec_once and clear_cc_filter calls in order."""

    def __init__(self):
        self.calls = []

    def cc_filter(self, value):
        self.calls.append(("filter", value))

    def cc_exec_once(self, cmd):
        self.calls.append(("exec", cmd))

    def clear_cc_filter(self):
        self.calls.append(("clear",))


def test_mm_cc_filter_clears_the_filter_on_exit_and_on_error():
    mm = _RecordingMM()
    with utils.mm_cc_filter(mm, "uuid=abc"):
        mm.cc_exec_once("true")
    with pytest.raises(RuntimeError), utils.mm_cc_filter(mm, "uuid=def"):
        raise RuntimeError("boom")

    assert mm.calls == [
        ("filter", "uuid=abc"),
        ("exec", "true"),
        ("clear",),
        ("filter", "uuid=def"),
        ("clear",),
    ]


def test_kill_and_delete_helpers_leave_no_filter_behind():
    mm = _RecordingMM()
    utils.mm_kill_process(mm, "uuid=abc", "iperf3")
    utils.mm_delete_file(mm, "uuid=abc", "/tmp/out.json")
    with pytest.raises(ValueError, match="unknown os_type"):
        utils.mm_kill_process(mm, "uuid=abc", "iperf3", os_type="beos")

    assert mm.calls == [
        ("filter", "uuid=abc"),
        ("exec", "pkill iperf3"),
        ("clear",),
        ("filter", "uuid=abc"),
        ("exec", "rm -f /tmp/out.json"),
        ("clear",),
        ("filter", "uuid=abc"),
        ("clear",),
    ]
