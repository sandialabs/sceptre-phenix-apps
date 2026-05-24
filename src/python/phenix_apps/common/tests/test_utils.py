import minimega
import pytest

from phenix_apps.common import utils


class _StubMM:
    """Stand-in for minimega.minimega whose cc_* methods replay per-call effects:
    a list (the per-host rows that cc fan-out returns) is returned, an Exception
    is raised (a transport-level failure). Mirrors _raise_errors so
    mm_cc_all_hosts can toggle it."""

    def __init__(self, effects=None, client_effects=None):
        self._effects = list(effects or [])
        self._client_effects = list(client_effects or [])
        self._raise_errors = True
        self.calls = 0
        self.client_calls = 0

    def cc_exitcode(self, *_args):
        self.calls += 1
        effect = self._effects.pop(0)

        if isinstance(effect, Exception):
            raise effect

        return effect

    def cc_clients(self, *_args):
        self.client_calls += 1
        effect = self._client_effects.pop(0)

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

    # A transport/namespace error (not a per-host data error) propagates.
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


# cc client returns one per-host response per cluster host; each carries a
# Tabular of registered miniccc clients on that host.
_CLIENTS_EMPTY = [{"Host": "gibson1337", "Header": [], "Tabular": [], "Error": ""}]
_CLIENTS_OTHER = [
    {
        "Host": "gibson1337",
        "Header": ["uuid", "hostname", "arch", "os"],
        "Tabular": [["zzz-9999", "bar", "amd64", "linux"]],
        "Error": "",
    }
]
_CLIENTS_MATCH = [
    {
        "Host": "gibson1336",
        "Header": ["uuid", "hostname", "arch", "os"],
        "Tabular": [["abc-1234", "foo", "amd64", "linux"]],
        "Error": "",
    }
]


def test_mm_cc_client_active_found_by_hostname():
    mm = _StubMM(client_effects=[_CLIENTS_MATCH])

    utils.mm_cc_client_active(mm, "foo", grace=60.0, poll_rate=0.0)

    assert mm.client_calls == 1


def test_mm_cc_client_active_found_by_uuid():
    mm = _StubMM(client_effects=[_CLIENTS_MATCH])

    utils.mm_cc_client_active(mm, "abc-1234", grace=60.0, poll_rate=0.0, by_uuid=True)

    assert mm.client_calls == 1


def test_mm_cc_client_active_polls_until_visible(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Two empty rounds (client not yet registered) before it appears.
    mm = _StubMM(client_effects=[_CLIENTS_EMPTY, _CLIENTS_OTHER, _CLIENTS_MATCH])

    utils.mm_cc_client_active(mm, "foo", grace=60.0, poll_rate=0.0)

    assert mm.client_calls == 3


def test_mm_cc_client_active_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Client never appears within the grace window.
    mm = _StubMM(client_effects=[_CLIENTS_EMPTY] * 3)

    with pytest.raises(RuntimeError):
        utils.mm_cc_client_active(mm, "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_active_ignores_non_matching_clients():
    # Other clients are registered, but ours isn't -- must NOT return.
    mm = _StubMM(client_effects=[_CLIENTS_OTHER])

    with pytest.raises(RuntimeError):
        utils.mm_cc_client_active(mm, "foo", grace=0.0, poll_rate=0.0)
