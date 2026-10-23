import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.iperf import iperf as iperf_module
from phenix_apps.apps.scorch.iperf.iperf import (
    Iperf,
    IperfMetadata,
    _pidfile_loop,
    _version_matches,
)
from phenix_apps.testing.readme import readme_components, readme_yaml

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "iperf")


def metadata(**overrides) -> dict:
    md = {
        "run_duration": 60.0,
        "iperf_paths": {"linux": "/usr/bin/iperf3"},
        "servers": [
            {
                "hostname": "srv",
                "port_range_start": 6201,
                "clients": [{"hostname": "c1"}, {"hostname": "c2"}],
            }
        ],
    }
    md.update(overrides)
    return md


def test_readme_has_examples():
    assert len(readme_examples()) == 3


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid(cmp):
    parse_metadata(IperfMetadata, cmp["metadata"], cmp["name"])


def test_filebeat_block_parses_and_is_kept():
    (block,) = readme_yaml(README, "Filebeat")
    md = metadata() | block["metadata"]

    config = parse_metadata(IperfMetadata, md, "i")
    assert config.model_extra is not None
    assert "filebeat.inputs" in config.model_extra


def test_defaults_match_the_old_code():
    config = parse_metadata(IperfMetadata, metadata(), "i")

    assert config.verify_execution is True
    assert config.create_histogram is True
    assert config.collect_netstat_info is False
    assert config.use_rperf is False
    assert config.server_startup_delay == 5.0
    assert config.client_port_offset == 1000
    assert config.stop_grace == 5.0


def test_unquoted_version_fails():
    with pytest.raises(ValueError, match="iperf_version"):
        parse_metadata(IperfMetadata, metadata(iperf_version=3.15), "i")


def two_servers(second_start: int, second_host: str = "srv2") -> list[dict]:
    first = metadata()["servers"][0]
    return [
        first,
        {
            "hostname": second_host,
            "port_range_start": second_start,
            "clients": [{"hostname": "c3"}],
        },
    ]


@pytest.mark.parametrize(
    ("md", "message"),
    [
        (
            metadata(servers=two_servers(6202)),
            "port 6202 .* already used by server srv",
        ),
        (metadata(servers=two_servers(64536)), "client port 65536"),
        (metadata(servers=[]), "servers"),
        (metadata(bandwidth=0), "bandwidth"),
        (metadata(add_client_args="--omit 2'; reboot; '"), "add_client_args"),
        (metadata(add_client_args="--omit 2; reboot"), "add_client_args"),
        (metadata(add_server_args="-V $(reboot)"), "add_server_args"),
        (metadata(add_client_args="--omit 2\\n reboot"), "add_client_args"),
        (metadata(add_client_args='--title "x'), "add_client_args"),
        (metadata(add_client_args="--omit 2 #"), "add_client_args"),
        (metadata(add_client_args="--json-stream"), "--json-stream is not supported"),
        (metadata(iperf_paths={"linux": "/usr/bin/iperf 3"}), "iperf_paths.linux"),
        (
            metadata(iperf_paths={"linux": "/usr/bin/iperf3;reboot"}),
            "iperf_paths.linux",
        ),
        (metadata(iperf_paths={"linux": "/usr/bin/$(reboot)"}), "iperf_paths.linux"),
        (metadata(iperf_version=" "), "iperf_version"),
        (metadata(client_port_offset=0), "client_port_offset"),
        (metadata(use_rperf=None), "use_rperf"),
        (metadata(verify_execution="maybe"), "verify_execution"),
        (metadata(verify_execution="false"), "verify_execution"),
        (metadata(run_duration="60"), "run_duration"),
        (metadata(run_duration=86396), "run_duration"),
        (metadata(iperf_paths={"linux": "C:\\iperf3.exe"}), "iperf_paths.linux"),
        (
            metadata(
                servers=[
                    {
                        "hostname": "bad_host",
                        "port_range_start": 6201,
                        "clients": [{"hostname": "c1"}],
                    }
                ]
            ),
            "hostname",
        ),
        (
            metadata(
                servers=[
                    {
                        "hostname": "srv",
                        "interface": "a-name-over-15-chars",
                        "port_range_start": 6201,
                        "clients": [{"hostname": "c1"}],
                    }
                ]
            ),
            "interface",
        ),
        (metadata(servers=two_servers(6301, "srv")), "servers listed more than once"),
        (
            metadata(
                servers=[
                    {
                        "hostname": "srv",
                        "port_range_start": 6201,
                        "clients": [{"hostname": "c1"}, {"hostname": "c1"}],
                    }
                ]
            ),
            "clients listed more than once: c1",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(IperfMetadata, md, "i")


def test_last_usable_port_is_accepted():
    parse_metadata(IperfMetadata, metadata(servers=two_servers(64535)), "i")


def node(hostname: str, os_type: str | None, address: str) -> dict:
    hardware = {"os_type": os_type} if os_type else {}
    return {
        "general": {"hostname": hostname},
        "hardware": hardware,
        "network": {"interfaces": [{"name": "eth0", "address": address}]},
    }


def component(md: dict, nodes: list[dict]) -> Iperf:
    """An Iperf with just the state the mapping helpers read; no minimega."""

    iperf = Iperf.__new__(Iperf)
    iperf.name = "i"
    iperf.exp_name = "exp"
    iperf.root_dir = Path(tempfile.mkdtemp())
    (iperf.root_dir / "exp").mkdir()
    iperf.config = parse_metadata(IperfMetadata, md, "i")
    iperf.experiment = Box({"spec": {"topology": {"nodes": nodes}}})
    return iperf


LINUX_NODES = [
    node("srv", "linux", "10.0.0.1"),
    node("c1", "Linux", "10.0.0.2"),
    node("c2", "linux", "10.0.0.3"),
]


def test_node_info_and_mapping():
    iperf = component(metadata(bandwidth=100), LINUX_NODES)

    info = iperf._get_node_info()
    assert info["vms"] == ["c1", "c2", "srv"]
    assert info["os_count"] == {"linux": 3}

    mapping = iperf._build_iperf_mapping()
    c2 = mapping.srv.clients.c2
    assert (c2.port, c2.ip, c2.exe_path) == (6202, "10.0.0.3", "/usr/bin/iperf3")
    assert c2.server_log_path == "/iperf_server-data_client-c2_server-srv.json"
    assert (c2.bandwidth, c2.add_client_args) == (100, None)
    assert c2.interface == "eth0"


def test_client_settings_override_the_top_level_ones():
    md = metadata(bandwidth=100, add_client_args="--omit 2")
    md["servers"][0]["clients"][1] |= {"bandwidth": 5, "add_server_args": "-V"}
    iperf = component(md, LINUX_NODES)

    clients = iperf._build_iperf_mapping().srv.clients
    assert (clients.c1.bandwidth, clients.c2.bandwidth) == (100, 5)
    assert clients.c1.add_client_args == clients.c2.add_client_args == "--omit 2"
    assert (clients.c1.add_server_args, clients.c2.add_server_args) == (None, "-V")


def two_interface_node(hostname: str) -> dict:
    nodes = node(hostname, "linux", "10.0.0.1")
    nodes["network"]["interfaces"].append({"name": "eth1", "address": "10.1.0.1"})
    return nodes


@pytest.mark.parametrize(
    ("interface", "ip"), [(0, "10.0.0.1"), (1, "10.1.0.1"), ("eth1", "10.1.0.1")]
)
def test_interface_is_selected_by_index_or_name(interface, ip):
    md = metadata()
    md["servers"][0]["interface"] = interface
    nodes = [two_interface_node("srv"), *LINUX_NODES[1:]]

    srv = component(md, nodes)._build_iperf_mapping().srv
    assert srv.ip == ip


@pytest.mark.parametrize(
    ("interface", "message"),
    [
        ("eth9", "interface eth9 does not exist on node srv"),
        (5, "interface 5 does not exist"),
    ],
)
def test_unknown_interface_is_reported(interface, message):
    md = metadata()
    md["servers"][0]["interface"] = interface

    with pytest.raises(ValueError, match=message):
        component(md, LINUX_NODES)._build_iperf_mapping()


@pytest.mark.parametrize(
    ("nodes", "message"),
    [
        (LINUX_NODES[:2], "node c2 does not exist"),
        (
            [*LINUX_NODES[:2], node("c2", "solaris", "10.0.0.3")],
            'unknown os_type "solaris" for c2',
        ),
        (
            [*LINUX_NODES[:2], node("c2", "windows", "10.0.0.3")],
            "c2 is windows, but iperf_paths.windows is not set",
        ),
    ],
)
def test_node_info_names_the_bad_host(nodes, message):
    with pytest.raises(ValueError, match=message):
        component(metadata(), nodes)._get_node_info()


class FakeMinimega:
    """Records which VM each backgrounded command was sent to."""

    def __init__(self):
        self.filter = ""
        self.background: list[tuple[str, str]] = []
        self.exec_once: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, str]] = []  # vm, file name, content

    def cc_filter(self, f):
        self.filter = f

    def cc_exec_once(self, cmd):
        self.exec_once.append((self.filter, cmd))

    def clear_cc_filter(self):
        self.filter = ""

    def cc_background(self, cmd):
        self.background.append((self.filter.removeprefix("uuid=u-"), cmd))


@pytest.fixture(autouse=True)
def by_uuid(monkeypatch):
    """No minimega: a VM named x has the uuid u-x; cc sends are recorded."""

    def filter_vm(mm, vm):
        mm.cc_filter(f"uuid=u-{vm}")
        return f"u-{vm}", "host"

    def send_wait(mm, vm, src, exp_name):
        mm.sent.append((vm, Path(src).name, Path(src).read_text()))

    monkeypatch.setattr(iperf_module.utils, "mm_cc_filter_vm", filter_vm)
    monkeypatch.setattr(iperf_module.utils, "mm_cc_send_wait", send_wait)


def test_start_builds_server_and_client_commands():
    md = metadata(server_startup_delay=0)
    md["servers"][0]["clients"] = [{"hostname": "c1"}, {"hostname": "win"}]
    nodes = [
        node("srv", "linux", "10.0.0.1"),
        node("c1", "linux", "10.0.0.2"),
        node("win", "windows", "10.0.0.9"),
    ]
    md["iperf_paths"]["windows"] = "/iperf3.exe"
    iperf = component(md, nodes)
    iperf._mm = FakeMinimega()

    iperf.start()
    cmds = dict(iperf._mm.background)
    servers = [cmd for vm, cmd in iperf._mm.background if vm == "srv"]

    # servers write their JSON results where stop() collects them
    assert all(
        "--logfile /iperf_server-data_client-" in cmd and cmd.endswith("2>&1'")
        for cmd in servers
    )
    assert cmds["c1"].startswith("bash -c '/usr/bin/iperf3 --client 10.0.0.1")
    assert ">/iperf_client-log_client-c1_server-srv.log 2>&1'" in cmds["c1"]
    # Windows has no bash
    assert cmds["win"].startswith("/iperf3.exe --client 10.0.0.1")
    assert "--cport 7202" in cmds["win"]


def test_unknown_key_only_warns():
    md = metadata(servers=[metadata()["servers"][0] | {"port_start": 1}])
    _, warnings = validate_metadata(IperfMetadata, md, "i")

    assert warnings == [
        "servers.0.port_start: unknown key, ignored. Fix: remove it "
        "(did you mean 'port_range_start'?)"
    ]


def test_clean_configs_have_no_warnings():
    for cmp in readme_examples():
        assert validate_metadata(IperfMetadata, cmp["metadata"], "i")[1] == []


def test_nested_typo_is_kept_but_unused():
    md = metadata()
    md["servers"][0]["clients"][0]["bitrate"] = 100
    config, warnings = validate_metadata(IperfMetadata, md, "i")

    assert config.servers[0].clients[0].bandwidth is None
    assert warnings == [
        "servers.0.clients.0.bitrate: unknown key, ignored. Fix: remove it "
        "(known: hostname, interface, add_server_args, add_client_args, bandwidth)"
    ]


def test_start_uses_the_client_port_offset():
    iperf = component(
        metadata(server_startup_delay=0, client_port_offset=500), LINUX_NODES
    )
    iperf._mm = FakeMinimega()

    iperf.start()

    assert any("--cport 6701" in cmd for _, cmd in iperf._mm.background)


def test_results_are_collected_with_one_transfer_per_vm(monkeypatch):
    calls = []
    monkeypatch.setattr(iperf_module.utils, "mm_recv", lambda **kw: calls.append(kw))
    iperf = component(metadata(), LINUX_NODES)
    iperf.base_dir = Path("/tmp/run")
    iperf._mm = object()
    mapping = iperf._build_iperf_mapping()

    iperf._collect_files(mapping, iperf._get_node_info())

    by_vm = {call["vm"]: call["src"] for call in calls}
    assert sorted(by_vm) == ["c1", "c2", "srv"]
    assert len(calls) == 3
    assert all(call["dst"] == "/tmp/run" for call in calls)
    assert by_vm["c1"] == [
        "/iperf_client-data_client-c1_server-srv.json",
        "/iperf_client-log_client-c1_server-srv.log",
    ]
    assert len(by_vm["srv"]) == 4  # a result and a log for each of two clients


def test_empty_add_args_are_valid():
    config = parse_metadata(IperfMetadata, metadata(add_client_args=""), "i")

    assert config.add_client_args == ""


def test_empty_client_args_switch_the_top_level_ones_off():
    md = metadata(add_client_args="--omit 2", add_server_args="-V")
    md["servers"][0]["clients"][0] |= {"add_client_args": "", "add_server_args": ""}
    iperf = component(md, LINUX_NODES)

    clients = iperf._build_iperf_mapping().srv.clients
    assert (clients.c1.add_client_args, clients.c1.add_server_args) == ("", "")
    assert (clients.c2.add_client_args, clients.c2.add_server_args) == (
        "--omit 2",
        "-V",
    )

    iperf._mm = FakeMinimega()
    iperf.config.server_startup_delay = 0
    iperf.start()
    cmds = [cmd for _, cmd in iperf._mm.background]
    c1 = next(c for c in cmds if "--cport 7201" in c)
    c2 = next(c for c in cmds if "--cport 7202" in c)
    assert "--omit" not in c1
    assert "--cport 7201 --pidfile /iperf_client-pid_client-c1_server-srv.pid >/" in c1
    assert "--omit 2" in c2


def test_start_uses_pid_files_on_linux_only():
    md = metadata(server_startup_delay=0)
    md["servers"][0]["clients"] = [{"hostname": "c1"}, {"hostname": "win"}]
    md["iperf_paths"]["windows"] = "/iperf3.exe"
    nodes = [
        node("srv", "linux", "10.0.0.1"),
        node("c1", "linux", "10.0.0.2"),
        node("win", "windows", "10.0.0.9"),
    ]
    iperf = component(md, nodes)
    iperf._mm = FakeMinimega()

    iperf.start()
    cmds = dict(iperf._mm.background)

    assert "--pidfile /iperf_client-pid_client-c1_server-srv.pid" in cmds["c1"]
    assert "--pidfile" not in cmds["win"]
    assert any(
        "--pidfile /iperf_server-pid_client-win_server-srv.pid" in cmd
        for vm, cmd in iperf._mm.background
        if vm == "srv"
    )


@pytest.mark.parametrize(
    ("run_duration", "time", "idle_timeout"),
    [(60.0, 60, 65), (0.5, 1, 6), (60.5, 61, 66)],
)
def test_iperf_gets_whole_seconds(run_duration, time, idle_timeout):
    # iperf3 reads --time with atoi: "0.5" would be 0, which never ends.
    iperf = component(
        metadata(run_duration=run_duration, server_startup_delay=0), LINUX_NODES
    )
    iperf._mm = FakeMinimega()

    iperf.start()
    cmds = [cmd for _, cmd in iperf._mm.background]

    assert any(f"--time {time} " in cmd for cmd in cmds)
    assert any(f"--idle-timeout {idle_timeout} " in cmd for cmd in cmds)


@pytest.mark.parametrize(
    ("output", "wanted", "tool", "ok"),
    [
        ("iperf 3.15 (cJSON 1.7.15)\nLinux", "3.15", "iperf", True),
        ("iperf 3.17.1 (cJSON 1.7.15)", "3.17", "iperf", True),
        ("iperf 3.17.1 (cJSON 1.7.15)", "3.17.1", "iperf", True),
        ("iperf 3.15 (cJSON 1.7.15)", "3.1", "iperf", False),
        ("iperf 3.20 (cJSON 1.7.15)", "3.2", "iperf", False),
        ("iperf 3.19.1 (cJSON 1.7.15)", "3.19.2", "iperf", False),
        ("rperf 0.1.8", "0.1.8", "rperf", True),
        ("rperf 0.1.8", "0.1", "rperf", True),
        ("something else 3.15", "3.15", "iperf", True),
    ],
)
def test_version_matches_whole_version_parts(output, wanted, tool, ok):
    assert _version_matches(output, wanted, tool) is ok


def test_process_names_come_from_the_mapping():
    md = metadata()
    md["iperf_paths"]["windows"] = "/tools/iperf3.exe"
    md["servers"][0]["clients"][1] = {"hostname": "win"}
    nodes = [*LINUX_NODES[:2], node("win", "windows", "10.0.0.9")]
    iperf = component(md, nodes)

    names = iperf._process_names(iperf._build_iperf_mapping(), iperf._get_node_info())

    assert names == {"linux": "iperf3", "windows": "iperf3.exe"}


class KillMinimega(FakeMinimega):
    def cc_process_killall(self, needle):
        self.exec_once.append((self.filter, f"killall {needle}"))


def killed(iperf: Iperf) -> list[tuple[str, str]]:
    iperf._mm = KillMinimega()
    iperf._kill_all_iperf(iperf._get_node_info(), iperf._build_iperf_mapping())
    return iperf._mm.exec_once


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(iperf_module, "sleep", lambda _: None)


@pytest.mark.usefixtures("no_sleep")
def test_linux_iperf_is_killed_through_its_pid_files():
    iperf = component(metadata(), LINUX_NODES)
    ((filter_, cmd),) = killed(iperf)

    assert filter_ == "iperf=1 os=linux"
    assert cmd == "bash /tmp/miniccc/files/exp/iperf-kill.sh"
    # the script goes to every Linux VM, with the loop that needs `$p`
    assert {vm for vm, _, _ in iperf._mm.sent} == {"srv", "c1", "c2"}
    (script,) = {body for _, name, body in iperf._mm.sent}
    assert script.startswith("for f in /iperf_*.pid; do ")
    assert 'kill "$p"' in script
    assert "pkill" not in script


@pytest.mark.usefixtures("no_sleep")
def test_rperf_is_still_killed_by_name():
    iperf = component(metadata(use_rperf=True), LINUX_NODES)
    iperf.config.iperf_paths.linux = "/usr/local/bin/rperf"

    assert killed(iperf) == [("iperf=1 os=linux", "pkill rperf")]


@pytest.mark.usefixtures("no_sleep")
@pytest.mark.usefixtures("no_sleep")
def test_windows_iperf_is_killed_through_miniccc():
    md = metadata()
    md["iperf_paths"]["windows"] = "/iperf3.exe"
    md["servers"][0]["clients"] = [{"hostname": "win"}]
    nodes = [node("srv", "linux", "10.0.0.1"), node("win", "windows", "10.0.0.9")]

    assert ("iperf=1 os=windows", "killall /iperf_") in killed(component(md, nodes))


def fake_proc(tmp_path: Path, pidfiles: dict[str, str], procs: dict[int, str]) -> str:
    """The pid-file loop, aimed at a temp directory standing in for / and /proc."""

    for name, content in pidfiles.items():
        (tmp_path / name).write_text(content)
    for pid, cmdline in procs.items():
        (tmp_path / "proc" / str(pid)).mkdir(parents=True)
        (tmp_path / "proc" / str(pid) / "cmdline").write_text(cmdline)
    script = _pidfile_loop("iperf3", "echo hit:$p")
    return script.replace("/iperf_", f"{tmp_path}/iperf_").replace(
        "/proc/", f"{tmp_path}/proc/"
    )


def test_pid_file_loop_only_acts_on_live_iperf_processes(tmp_path):
    script = fake_proc(
        tmp_path,
        {
            "iperf_a.pid": "111",  # running iperf3
            "iperf_b.pid": "222",  # pid reused by another program
            "iperf_c.pid": "333",  # process is gone
            "iperf_d.pid": "x; reboot",  # not a pid
            "iperf_e.pid": "",
        },
        {111: "/usr/bin/iperf3\0--server", 222: "/usr/bin/sleep\0 30"},
    )

    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )

    assert out.stdout.split() == ["hit:111"]


def test_pid_file_loop_with_no_pid_files_does_nothing(tmp_path):
    script = fake_proc(tmp_path, {}, {})

    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )

    assert out.stdout == ""


class RunningIperf(Iperf):
    """An Iperf whose VMs answer the running-check with canned stdout."""

    def __init__(self, stdout: dict[str, str]):
        self.answers = stdout
        self.cmds: list[str] = []
        self.sent: list[str] = []

    def _send_script(self, node_info, name, body):
        self.sent.append(body)
        return f"bash /tmp/miniccc/files/exp/{name}"

    def _run_multi(self, cmd, cc_filter, prefix, num_responses, timeout=10.0):
        self.cmds.append(cmd)
        return [{"stdout": self.answers[prefix]}] * num_responses


@pytest.mark.parametrize(
    ("linux", "running"), [("running=0\n", False), ("running=2\n", True)]
)
def test_iperf_running_checks_every_vm(linux, running):
    base = component(metadata(), LINUX_NODES)
    iperf = RunningIperf({"iperf_running_linux": linux})
    iperf.config, iperf.experiment = base.config, base.experiment

    result = iperf._iperf_running(base._get_node_info(), base._build_iperf_mapping())

    assert result is running


# minimega expands a bare `$name` in an inline cc command before the VM sees it;
# `$(...)` survives.
BARE_VARIABLE = re.compile(r"\$(?!\()[A-Za-z_@$]")


@pytest.mark.usefixtures("no_sleep")
def test_inline_cc_commands_have_no_bare_variables():
    md = metadata(server_startup_delay=0)
    md["iperf_paths"]["windows"] = "/iperf3.exe"
    md["servers"][0]["clients"] = [{"hostname": "c1"}, {"hostname": "win"}]
    nodes = [
        node("srv", "linux", "10.0.0.1"),
        node("c1", "linux", "10.0.0.2"),
        node("win", "windows", "10.0.0.9"),
    ]
    iperf = component(md, nodes)
    iperf._mm = KillMinimega()
    iperf.start()
    iperf._kill_all_iperf(iperf._get_node_info(), iperf._build_iperf_mapping())
    inline = [cmd for _, cmd in iperf._mm.background + iperf._mm.exec_once]

    running = RunningIperf(
        {"iperf_running_linux": "running=0", "iperf_running_windows": ""}
    )
    running.config, running.experiment = iperf.config, iperf.experiment
    running._iperf_running(iperf._get_node_info(), iperf._build_iperf_mapping())
    inline += running.cmds

    assert len(inline) > 5
    assert [c for c in inline if BARE_VARIABLE.search(c)] == []
    # the variables are in the scripts, which minimega does not expand
    assert any(BARE_VARIABLE.search(body) for body in running.sent)
    assert running.cmds[0] == "bash /tmp/miniccc/files/exp/iperf-running.sh"


def test_vms_are_targeted_by_uuid():
    iperf = component(metadata(server_startup_delay=0), LINUX_NODES)
    iperf._mm = FakeMinimega()
    filters = []
    iperf._mm.cc_background = lambda cmd: filters.append(iperf._mm.filter)

    iperf.start()

    assert set(filters) == {"uuid=u-srv", "uuid=u-c1", "uuid=u-c2"}
