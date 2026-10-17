from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.iperf import iperf as iperf_module
from phenix_apps.apps.scorch.iperf.iperf import Iperf, IperfMetadata
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
        (metadata(iperf_paths={"linux": "/usr/bin/iperf 3"}), "iperf_paths.linux"),
        (metadata(iperf_version=" "), "iperf_version"),
        (metadata(client_port_offset=0), "client_port_offset"),
        (metadata(use_rperf=None), "use_rperf"),
        (metadata(verify_execution="maybe"), "verify_execution"),
        (metadata(verify_execution="false"), "verify_execution"),
        (metadata(run_duration="60"), "run_duration"),
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
        (LINUX_NODES[:2], "iperf hosts not in the topology: c2"),
        ([*LINUX_NODES[:2], node("c2", None, "10.0.0.3")], 'unknown os_type "" for c2'),
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

    def cc_filter(self, f):
        self.filter = f

    def clear_cc_filter(self):
        self.filter = ""

    def cc_background(self, cmd):
        self.background.append((self.filter.removeprefix("name="), cmd))


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
