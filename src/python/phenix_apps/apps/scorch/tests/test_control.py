import copy
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.control import ScopedCC


class Namespace:
    def __init__(self):
        self.filter = None
        self.prefix = ""
        self.commands = []
        self.deleted = []


class Connection:
    def __init__(self, namespace):
        self.state = namespace
        self._raise_errors = True

    def clear_cc_filter(self):
        self.state.filter = None

    def clear_cc_prefix(self):
        self.state.prefix = ""

    def cc_filter(self, value=None):
        self.state.filter = value

    def cc_prefix(self, value=None):
        self.state.prefix = value

    def cc_exec(self, command):
        if command == "fail":
            raise RuntimeError("submission failed")
        self.state.commands.append(
            [
                str(len(self.state.commands)),
                self.state.prefix,
                command,
                self.state.filter,
            ]
        )
        return [{"Response": str(len(self.state.commands) - 1)}]

    def cc_commands(self):
        return [
            {
                "Header": ["id", "prefix", "command", "filter"],
                "Tabular": copy.deepcopy(self.state.commands),
            }
        ]

    def cc_delete_command(self, prefix):
        self.state.deleted.append(prefix)
        self.state.commands = [row for row in self.state.commands if row[1] != prefix]

    def cc_delete_response(self, prefix):
        self.state.deleted.append(prefix)

    def clear_cc_commands(self):
        pytest.fail("unscoped namespace reset")

    def clear_cc_responses(self):
        pytest.fail("unscoped namespace reset")


def test_concurrent_connections_keep_filter_prefix_and_reset_independent(tmp_path):
    state = Namespace()
    setup = ScopedCC(Connection(state), "experiment", "setup-component", str(tmp_path))
    work = ScopedCC(Connection(state), "experiment", "work-component", str(tmp_path))
    setup.cc_filter("name=setup-vm")
    work.cc_filter("name=work-vm")
    setup.cc_prefix("capture")
    work.cc_prefix("capture")
    ready = threading.Barrier(2)

    def submit(client):
        ready.wait()
        for index in range(30):
            client.cc_exec(f"command-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, client) for client in (setup, work)]
        for future in futures:
            future.result(timeout=5)

    assert len(state.commands) == 60
    for row in state.commands:
        assert row[3] == (
            "name=setup-vm" if row[1].startswith("scorch-setup") else "name=work-vm"
        )
    owned = setup.cc_commands()[0]["Tabular"]
    assert len(owned) == 30
    assert all(row[1] == "capture" for row in owned)
    setup.cc_delete_command("all")
    setup.cc_delete_response("all")
    setup.clear_cc_commands()
    setup.clear_cc_responses()
    assert len(work.cc_commands()[0]["Tabular"]) == 30
    assert state.deleted == ["scorch-setup-component-capture"] * 2
    assert state.filter is None
    assert state.prefix == ""


def test_submission_failure_releases_lock_and_clears_namespace(tmp_path):
    state = Namespace()
    client = ScopedCC(Connection(state), "experiment", "owner", str(tmp_path))
    client.cc_filter("name=vm")
    with pytest.raises(RuntimeError, match="submission failed"):
        client.cc_exec("fail")
    client.cc_exec("next")
    assert len(state.commands) == 1
    assert state.filter is None
    assert state.prefix == ""


def test_error_policy_is_forwarded(tmp_path):
    connection = Connection(Namespace())
    client = ScopedCC(connection, "experiment", "owner", str(tmp_path))
    client._raise_errors = False
    assert connection._raise_errors is False
    assert client._raise_errors is False


def test_capability_probe_needs_no_experiment(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["component", "--scorch-capabilities"])
    with pytest.raises(SystemExit) as result:
        ComponentBase.check_args()
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == '{"scorchConcurrencyProtocol": 1}'


def test_numeric_deletion_cannot_confuse_host_local_ids(tmp_path):
    client = ScopedCC(Connection(Namespace()), "experiment", "owner", str(tmp_path))
    with pytest.raises(ValueError, match="host-local"):
        client.cc_delete_command("1")


def _process_submit(state, barrier, directory, owner):
    client = ScopedCC(Connection(state), "experiment", owner, directory)
    client.cc_filter(f"name={owner}")
    client.cc_prefix("capture")
    barrier.wait(timeout=5)
    for index in range(20):
        client.cc_exec(f"command-{index}")


def test_processes_share_the_namespace_lock(tmp_path):
    context = multiprocessing.get_context("fork")
    with context.Manager() as manager:
        state = manager.Namespace()
        state.filter = None
        state.prefix = ""
        state.commands = manager.list()
        barrier = context.Barrier(2)
        processes = [
            context.Process(
                target=_process_submit, args=(state, barrier, str(tmp_path), owner)
            )
            for owner in ("setup", "work")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join()
            assert process.exitcode == 0
        assert len(state.commands) == 40
        for row in state.commands:
            assert row[3] == (
                "name=setup" if row[1].startswith("scorch-setup") else "name=work"
            )
