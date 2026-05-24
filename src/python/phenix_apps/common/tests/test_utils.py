import minimega
import pytest

from phenix_apps.common import utils


# Derive the transient and permanent cases from the lists in utils.py
@pytest.mark.parametrize("token", utils._MM_TRANSIENT)
def test_transient_tokens_classify_transient(token):
    assert utils.is_transient_mm_error(minimega.Error(token)) is True


@pytest.mark.parametrize("token", utils._MM_PERMANENT)
def test_permanent_tokens_classify_permanent(token):
    assert utils.is_transient_mm_error(minimega.Error(token)) is False


# Cases not in the lists
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Transient wrapped
        ("unable to get exit code: no client foo", True),
        # Permanent wrapped
        ("no such handler: can't handle this", False),
        # Permanent + transient -> permanent wins
        (
            "vm not running: connection reset by peer",
            False,
        ),
        # Not in either list -> default False
        (
            "something that does not exist in either list",
            False,
        ),
    ],
)
def test_is_transient_mm_error_messages(text, expected):
    assert utils.is_transient_mm_error(minimega.Error(text)) is expected


class _StubMM:
    """Stand-in for minimega.minimega whose cc_exitcode replays per-call effects:
    a list (the per-host rows that cc fan-out returns) is returned, an Exception
    is raised (a transport-level failure). Mirrors _raise_errors so
    mm_cc_all_hosts can toggle it."""

    def __init__(self, effects):
        self._effects = list(effects)
        self._raise_errors = True
        self.calls = 0

    def cc_exitcode(self, *_args):
        self.calls += 1
        effect = self._effects.pop(0)

        if isinstance(effect, Exception):
            raise effect

        return effect


# Multi-host cc_exitcode fan-out: the sibling host that doesn't run the VM
# reports "no client"; only the VM's host carries the code.
_SIBLING_ONLY = [{"Host": "gibson1337", "Error": "no client foo", "Response": ""}]
_WITH_CODE = [
    {"Host": "gibson1337", "Error": "no client foo", "Response": ""},
    {"Host": "gibson1336", "Error": "", "Response": "0"},
]


def test_mm_cc_all_hosts_returns_all_rows_and_restores_raise_errors():
    mm = _StubMM([_WITH_CODE])

    out = utils.mm_cc_all_hosts(mm, mm.cc_exitcode, "1", "foo")

    assert out == _WITH_CODE  # sibling error row NOT dropped
    assert mm._raise_errors is True  # restored after the call


def test_mm_cc_exitcode_wait_picks_host_with_code_ignoring_sibling(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Sibling reports "no client" twice before the VM's host records the code.
    mm = _StubMM([_SIBLING_ONLY, _SIBLING_ONLY, _WITH_CODE])

    row = utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=60.0, poll_rate=0.0)

    assert row["Response"] == "0"
    assert mm.calls == 3


def test_mm_cc_exitcode_wait_transport_error_raises_immediately(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # A permanent transport/namespace error (not a per-host data error) is not
    # retried.
    mm = _StubMM([minimega.Error("vm not found: foo")])

    with pytest.raises(minimega.Error):
        utils.mm_cc_exitcode_wait(mm, "1", "foo")

    assert mm.calls == 1


def test_mm_cc_exitcode_wait_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # No host ever reports the code (e.g. the client never came back).
    mm = _StubMM([_SIBLING_ONLY] * 5)

    with pytest.raises(RuntimeError):
        utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=0.0, poll_rate=0.0)


def test_mm_command_id_reads_data_field():
    # minimega returns the new command id (an int) in the Data field; it must be
    # stringified to match the string id in `cc commands` tabular output.
    resp = [{"Host": "headnode", "Data": 36, "Error": ""}]

    assert utils.mm_command_id(resp) == "36"


def test_mm_command_id_picks_host_carrying_data():
    # On multi-host, only the host that created the command carries Data; others
    # may report Data=None. The id must still be found.
    resp = [
        {"Host": "gibson1337", "Data": None, "Error": ""},
        {"Host": "gibson1336", "Data": 7, "Error": ""},
    ]

    assert utils.mm_command_id(resp) == "7"


def test_mm_command_id_missing_data_raises():
    with pytest.raises(RuntimeError):
        utils.mm_command_id([{"Host": "headnode", "Data": None, "Error": ""}])
