"""Tests for the pre-start handlers.

Covers the branches worth guarding: interface selection, fdlist zero-filling,
OPC primary-vs-backup routing, and the two preserved bugs.
"""

from types import SimpleNamespace

import pytest

from phenix_apps.apps.sceptre.app import Sceptre
from phenix_apps.apps.sceptre.prestart import PreStart
from phenix_apps.apps.sceptre.tests.conftest import iface, node

pytestmark = pytest.mark.app_class(cls=Sceptre, name="sceptre")


def fake_opc_config(channel_name):
    """Minimal stand-in for configs.OpcConfig: just what HistorianConfig reads."""
    tag = SimpleNamespace(devname="bus-1", regtype="analog-input", field="voltage")
    device = SimpleNamespace(fd_name="rtu-1", tags=[tag])
    channel = SimpleNamespace(name=channel_name, devices=[device])
    return SimpleNamespace(channel_list=[channel])


def fd_server(hostname, interfaces, **metadata):
    """Build an fd-server host with one dnp3 bus, overridable via **metadata."""

    metadata = {
        "provider": "provider-1",
        "infrastructure": "power-transmission",
        "dnp3": [{"type": "bus", "name": f"bus-{hostname}"}],
        **metadata,
    }
    return node(hostname, metadata, interfaces=interfaces)


@pytest.fixture
def ctx_with_provider(sceptre_app):
    """A pre-start stage already carrying the provider fd-servers look up."""

    ctx = PreStart(sceptre_app)
    ctx.provider_map["provider-1"] = node(
        "provider-1",
        {"simulator": "PowerWorld", "publish_endpoint": "udp://*;239.0.0.1:40000"},
        interfaces=[iface("IF0", "10.0.0.1")],
    )
    return ctx


class TestProviderConfigs:
    def test_powerworld_helics_is_in_both_families(self, sceptre_app):
        """PowerWorldHelics sits in POWER_WORLD_FAMILY and HELICS_FAMILY: its
        config.ini needs the case files and the helics.json path."""

        provider = node(
            "provider-1",
            {"simulator": "PowerWorldHelics"},
            interfaces=[iface("IF0", "10.0.0.1")],
        )
        sceptre_app.extract_nodes_type.return_value = [provider]
        sceptre_app.extract_nodes_label.return_value = []

        ctx = PreStart(sceptre_app)
        ctx.provider_configs()

        kwargs = sceptre_app.render.call_args.kwargs
        assert kwargs["solver"] == "PowerWorldHelics"
        assert kwargs["case_file"] == "case.PWB"
        assert kwargs["oneline_file"] == "oneline.pwd"
        assert kwargs["config_helics"] == "/etc/sceptre/helics.json"


class TestFdServerInterfaceSelection:
    """The tcp address a field device binds to depends on interface type/vlan."""

    @pytest.mark.parametrize(
        ("interfaces", "expected_ip"),
        [
            pytest.param(
                [iface("IF0", "172.16.0.1", vlan="mgmt"), iface("IF1", "10.2.0.1")],
                "10.2.0.1",
                id="skips-mgmt",
            ),
            pytest.param(
                [
                    iface("IF0", "10.2.0.1"),
                    iface("IF1", "10.2.0.9", vlan="other"),
                ],
                "10.2.0.1",
                id="first-non-mgmt-wins",
            ),
            pytest.param(
                [
                    iface("IF0", "172.16.0.1", vlan="MGMT"),
                    iface("IF1", "10.2.0.1"),
                ],
                "10.2.0.1",
                id="uppercase-MGMT-skipped-too-this-block-lowercases",
            ),
            pytest.param(
                [
                    iface("IF0", "10.2.0.1", kind="serial", device="/dev/ttyS0"),
                    iface("IF1", "10.2.0.2"),
                ],
                "10.2.0.1",
                id="exactly-two-ifaces-lets-a-serial-one-supply-tcp",
            ),
        ],
    )
    def test_selects_tcp_address(
        self, sceptre_app, ctx_with_provider, interfaces, expected_ip
    ):
        sceptre_app.extract_nodes_type.return_value = [fd_server("rtu-1", interfaces)]

        ctx_with_provider.fd_servers()

        assert ctx_with_provider.fd_server_configs["rtu-1"].ipaddr == expected_ip

    def test_mgmt_interface_binds_the_publish_endpoint(
        self, sceptre_app, ctx_with_provider
    ):
        """The provider publishes to udp://*, but the RTU must bind to mgmt."""
        sceptre_app.extract_nodes_type.return_value = [
            fd_server(
                "rtu-1",
                [iface("IF0", "172.16.0.5", vlan="mgmt"), iface("IF1", "10.2.0.1")],
            )
        ]

        ctx_with_provider.fd_servers()

        assert ctx_with_provider.fd_server_configs["rtu-1"].publish_endpoint == (
            "udp://172.16.0.5;239.0.0.1:40000"
        )

    def test_serial_devices_are_collected(self, sceptre_app, ctx_with_provider):
        sceptre_app.extract_nodes_type.return_value = [
            fd_server(
                "rtu-1",
                [
                    iface("IF0", "10.2.0.1"),
                    iface("IF1", "10.9.0.1", kind="serial", device="/dev/ttyS0"),
                ],
                **{"dnp3-serial": [{"type": "bus", "name": "bus-s"}]},
            )
        ]

        ctx_with_provider.fd_servers()

        assert ctx_with_provider.fd_server_configs["rtu-1"].serial_dev == []


class TestRegisterOverrides:
    def test_an_override_replaces_the_default_fields(
        self, sceptre_app, ctx_with_provider
    ):
        """Metadata -> parser -> create_device -> the device's register list.

        A bus normally exposes seven analog-read fields; this asks for one.
        """

        sceptre_app.extract_nodes_type.return_value = [
            fd_server(
                "rtu-1",
                [iface("IF0", "10.2.0.1")],
                dnp3=[{"type": "bus", "name": "bus-1", "analog-read": ["voltage"]}],
            )
        ]

        ctx_with_provider.fd_servers()

        device = ctx_with_provider.fd_server_configs["rtu-1"].protocols[0].devices[0]
        analog = [r.field for r in device.registers if r.regtype == "analog-input"]
        assert analog == ["voltage"]


class TestFeps:
    """A fep fronts the fd-servers it adopts, and takes their devices with it."""

    def build(self, sceptre_app, ctx, fep_metadata=None, interfaces=None):
        """Run fd_servers for rtu-1, then feps for a fep that adopts it."""

        sceptre_app.extract_nodes_type.return_value = [
            fd_server("rtu-1", [iface("IF0", "10.2.0.11")])
        ]
        ctx.fd_servers()

        fep = node(
            "fep-1",
            {
                "provider": "provider-1",
                "infrastructure": "power-transmission",
                "connected_rtus": ["rtu-1"],
                **(fep_metadata or {}),
            },
            interfaces=interfaces
            or [iface("IF0", "172.16.0.30", vlan="mgmt"), iface("IF1", "10.2.0.30")],
        )
        sceptre_app.extract_nodes_type.return_value = [fep]
        ctx.feps()
        return ctx.fd_server_configs["fep-1"]

    def test_adopting_an_rtu_replaces_it(self, sceptre_app, ctx_with_provider):
        """The OPC and ELK handlers must see the fep, not the RTU behind it."""

        config = self.build(sceptre_app, ctx_with_provider)

        assert "rtu-1" not in ctx_with_provider.fd_server_configs
        assert [d.device_name for p in config.protocols for d in p.devices] == [
            "bus-rtu-1"
        ]

    def test_subtype_reaches_the_config(self, sceptre_app, ctx_with_provider):
        """Omitting it used to raise TypeError, so no fep could be built."""

        assert self.build(sceptre_app, ctx_with_provider).device_subtype == "single"

        second = PreStart(sceptre_app)
        second.provider_map = ctx_with_provider.provider_map
        built = self.build(sceptre_app, second, {"subtype": "multi"})

        assert built.device_subtype == "multi"

    def test_without_a_mgmt_interface_it_binds_what_it_has(
        self, sceptre_app, ctx_with_provider
    ):
        """These used to be assigned only inside the mgmt branch."""

        config = self.build(
            sceptre_app, ctx_with_provider, interfaces=[iface("IF0", "10.2.0.30")]
        )

        assert config.server_endpoint == "tcp://10.2.0.30:1330"


class TestServerEndpoint:
    def test_defaults_to_the_provider(self, sceptre_app, ctx_with_provider):
        sceptre_app.extract_nodes_type.return_value = [
            fd_server("rtu-1", [iface("IF0", "10.2.0.11")])
        ]

        ctx_with_provider.fd_servers()

        endpoint = ctx_with_provider.fd_server_configs["rtu-1"].server_endpoint
        assert endpoint == "tcp://10.0.0.1:5555"

    def test_server_hostname_points_it_somewhere_else(
        self, sceptre_app, ctx_with_provider
    ):
        """The named host is looked up as a bare topology node, not as a host."""

        sceptre_app.extract_nodes_type.return_value = [
            fd_server("rtu-1", [iface("IF0", "10.2.0.11")], server_hostname="relay-1")
        ]
        sceptre_app.extract_node.return_value = node(
            "relay-1", interfaces=[iface("IF0", "10.9.0.9")]
        ).topology

        ctx_with_provider.fd_servers()

        endpoint = ctx_with_provider.fd_server_configs["rtu-1"].server_endpoint
        assert endpoint == "tcp://10.9.0.9:5555"


class TestFdlist:
    def test_known_protocols_get_a_local_port_entry(
        self, sceptre_app, ctx_with_provider
    ):
        sceptre_app.extract_nodes_type.return_value = [
            fd_server("rtu-1", [iface("IF0", "10.2.0.1")])
        ]

        ctx_with_provider.fd_servers()

        assert ctx_with_provider.fdlist["rtu-1"]["20000-local"] == 1

    def test_unused_protocol_ports_are_zero_filled(
        self, sceptre_app, ctx_with_provider
    ):
        """Backwards compatibility: consumers expect all four keys to exist."""
        sceptre_app.extract_nodes_type.return_value = [
            fd_server("rtu-1", [iface("IF0", "10.2.0.1")])
        ]

        ctx_with_provider.fd_servers()

        entry = ctx_with_provider.fdlist["rtu-1"]
        assert entry["502-local"] == 0
        assert entry["47808-local"] == 0
        assert entry["2404-local"] == 0
        assert entry["9990-remote"] == 1


class TestWritePowerObjects:
    def test_merges_hil_tags_deduplicates_and_sorts(self, sceptre_app, tmp_path):
        objects = tmp_path / "objects.txt"
        ctx = PreStart(sceptre_app)
        ctx.objects_file_path = str(objects)
        ctx.power_object_list = ["gen-2", "bus-1", "gen-2"]
        ctx.hil_object_list = ["hil-9", "bus-1"]

        ctx.power_objects()

        assert objects.read_text().split("\n") == ["bus-1", "gen-2", "hil-9"]

    def test_writes_nothing_without_a_powerworld_provider(self, sceptre_app, tmp_path):
        ctx = PreStart(sceptre_app)
        ctx.power_object_list = ["gen-1"]

        ctx.power_objects()

        assert not list(tmp_path.rglob("objects.txt"))


class TestCollectScadaHistorianIps:
    def test_lowercase_mgmt_is_excluded_but_uppercase_is_not(self, sceptre_app):
        """The opc/scada/historian blocks compare vlan case-sensitively.

        fd-server code uses .lower() != "mgmt"; this code does not. Pinned
        because the inconsistency is load-bearing for which IPs end up here.
        """
        ctx = PreStart(sceptre_app)
        sceptre_app.extract_nodes_type.side_effect = [
            [  # scada-server
                node(
                    "scada-1",
                    interfaces=[
                        iface("IF0", "172.16.0.1", vlan="mgmt"),
                        iface("IF1", "10.1.0.1", vlan="scada"),
                    ],
                )
            ],
            [  # historian
                node(
                    "hist-1",
                    interfaces=[
                        iface("IF0", "172.16.0.2", vlan="MGMT"),
                        iface("IF1", "10.1.0.2", vlan="scada"),
                    ],
                )
            ],
        ]

        ctx.collect_ips()

        assert ctx.scada_ips == ["10.1.0.1"]
        assert ctx.historian_ips == ["172.16.0.2", "10.1.0.2"]


class TestOpcs:
    @pytest.mark.parametrize(
        ("hostname", "expected_bucket"),
        [
            ("opc-1", "opc_configs"),
            ("opc-primary", "opc_configs"),
            ("opc-secondary", "opc_bak_configs"),
            ("opc-bak", "opc_bak_configs"),
        ],
    )
    def test_hostname_routes_primary_vs_backup(
        self, sceptre_app, hostname, expected_bucket
    ):
        ctx = PreStart(sceptre_app)
        sceptre_app.extract_nodes_type.return_value = [
            node(hostname, interfaces=[iface("IF0", "10.1.0.40", vlan="scada")])
        ]

        ctx.opcs()

        assert list(getattr(ctx, expected_bucket)) == ["10.1.0.40"]


class TestHistorians:
    def test_no_opc_on_the_subnet_means_no_tags(self, sceptre_app, caplog):
        """hist-1 is on 10.7.0.x, the only OPC on 10.1.0.x.

        It used to inherit whichever config the OPC and SCADA loops left behind
        and list that OPC's devices, with no address to collect them from.
        """
        ctx = PreStart(sceptre_app)
        ctx.opc_configs = {"10.1.0.40": fake_opc_config("ChannelMatched")}
        ctx.historian_hosts = [
            node("hist-1", {}, interfaces=[iface("IF0", "10.7.0.80", vlan="scada3")])
        ]

        ctx.historians()

        kwargs = next(
            c.kwargs
            for c in sceptre_app.render.call_args_list
            if c.args[0] == "historian_config.mako"
        )
        assert kwargs["hist_config"].opc_ip == ""
        assert not kwargs["hist_config"].tags
        assert "no OPC server on subnet 10.7.0.80" in caplog.text

    def test_the_opc_on_its_own_subnet_wins(self, sceptre_app):
        ctx = PreStart(sceptre_app)
        ctx.opc_configs = {
            "10.1.0.40": fake_opc_config("ChannelOne"),
            "10.7.0.40": fake_opc_config("ChannelSeven"),
        }
        ctx.historian_hosts = [
            node("hist-1", {}, interfaces=[iface("IF0", "10.7.0.80", vlan="scada3")])
        ]

        ctx.historians()

        kwargs = next(
            c.kwargs
            for c in sceptre_app.render.call_args_list
            if c.args[0] == "historian_config.mako"
        )
        assert kwargs["hist_config"].opc_ip == "10.7.0.40"
        assert list(kwargs["hist_config"].tags) == ["ChannelSeven_DeviceRtu_1"]

    def test_backup_historian_gets_an_empty_config(self, sceptre_app):
        ctx = PreStart(sceptre_app)
        ctx.historian_hosts = [
            node("hist-bak", {}, interfaces=[iface("IF0", "10.1.0.81", vlan="scada")])
        ]

        ctx.historians()

        kwargs = next(
            c.kwargs
            for c in sceptre_app.render.call_args_list
            if c.args[0] == "historian_config.mako"
        )
        assert kwargs["hist_config"].tags == {}
