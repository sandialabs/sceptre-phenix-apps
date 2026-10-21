"""Tests for the build-time outstation point map and the DNP3 numbering it mirrors."""

import lxml.etree as ET
import pytest
from box import Box

from phenix_apps.apps.otsim.device import Register
from phenix_apps.apps.otsim.points import OutstationPoint, Outstations
from phenix_apps.apps.otsim.protocols.dnp3 import DNP3, assign_addresses
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.apps.otsim.protocols.protocol import resolve_endpoint

# Captured from the pre-refactor registers_to_xml for the registers below.
GOLDEN_OUTSTATION = """\
<dnp3 name="dnp3-outstation" mode="server">
  <endpoint>10.0.0.2:20001</endpoint>
  <outstation name="dnp3-outstation">
    <local-address>1024</local-address>
    <remote-address>1</remote-address>
    <input type="analog">
      <address>0</address>
      <tag>cap1.voltage</tag>
      <sgvar>30:5</sgvar>
      <egvar>32:7</egvar>
      <class>1</class>
    </input>
    <output type="analog">
      <address>0</address>
      <tag>cap1.setpt</tag>
      <sbo>True</sbo>
    </output>
    <input type="binary">
      <address>0</address>
      <tag>brk.status</tag>
      <class>2</class>
    </input>
    <output type="binary">
      <address>0</address>
      <tag>brk.controls</tag>
      <sgvar>10:2</sgvar>
      <sbo>False</sbo>
    </output>
    <input type="analog">
      <address>1</address>
      <tag>cap2.voltage</tag>
    </input>
    <output type="analog">
      <address>1</address>
      <tag>cap2.setpt</tag>
    </output>
  </outstation>
</dnp3>
"""

GOLDEN_REGISTERS = [
    Register(
        "analog-read", "cap1.voltage", {"sgvar": "30:5", "egvar": "32:7", "class": "1"}
    ),
    Register("analog-read-write", "cap1.setpt", {"sbo": True}),
    Register("binary-read", "brk.status", {"class": "2"}),
    Register("binary-read-write", "brk.controls", {"sgvar": "10:2", "sbo": False}),
    Register("analog-read", "cap2.voltage"),
    Register("bogus", "x.y"),
    Register("analog-read-write", "cap2.setpt"),
]


def node(hostname, metadata, interfaces=None):
    if interfaces is None:
        interfaces = [{"name": "eth0", "address": f"10.0.0.{len(hostname)}"}]
    return Box(
        {
            "hostname": hostname,
            "metadata": metadata,
            "topology": {"network": {"interfaces": interfaces}},
        }
    )


def test_registers_to_xml_output_is_unchanged():
    rtu = node("rtu", {"dnp3": {"interface": "eth1:20001", "devices": []}})
    rtu.topology.network.interfaces = [
        {"name": "eth0", "address": "10.0.0.1"},
        {"name": "eth1", "address": "10.0.0.2"},
    ]
    server = DNP3()
    server.init_xml_root("server", rtu)
    server.init_outstation_xml()
    server.registers_to_xml(GOLDEN_REGISTERS)
    assert ET.tostring(server.root, pretty_print=True).decode() == GOLDEN_OUTSTATION


def test_assign_addresses_counts_per_kind_and_skips_unknown_types():
    points = [(k, i, r.tag) for k, i, r in assign_addresses(GOLDEN_REGISTERS)]
    assert points == [
        ("ai", 0, "cap1.voltage"),
        ("ao", 0, "cap1.setpt"),
        ("bi", 0, "brk.status"),
        ("bo", 0, "brk.controls"),
        ("ai", 1, "cap2.voltage"),
        ("ao", 1, "cap2.setpt"),
    ]


def test_assign_addresses_continues_shared_counters():
    addrs = {"ai": 5, "ao": 0, "bi": 0, "bo": 0}
    (point,) = assign_addresses([Register("analog-read", "a.b")], addrs)
    assert point[:2] == ("ai", 5)
    assert addrs["ai"] == 6


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"dnp3": []}, ("10.0.0.1", 20000)),
        ({"dnp3": {"devices": []}}, ("10.0.0.1", 20000)),
        ({"dnp3": {"interface": "eth1"}}, ("10.0.0.2", 20000)),
        ({"dnp3": {"interface": "eth1:20001"}}, ("10.0.0.2", 20001)),
        ({"dnp3": {"interface": "192.0.2.9:1234"}}, ("192.0.2.9", 1234)),
        ({"dnp3": {"interface": "fe80::1"}}, ("fe80::1", 20000)),
        ({"dnp3": {"interface": "[fe80::1]:1234"}}, ("fe80::1", 1234)),
        ({}, ("10.0.0.1", 20000)),
    ],
)
def test_resolve_endpoint(metadata, expected):
    rtu = node(
        "rtu",
        metadata,
        [
            {"name": "eth0", "address": "10.0.0.1"},
            {"name": "eth1", "address": "10.0.0.2"},
        ],
    )
    assert resolve_endpoint(rtu, "dnp3", 20000) == expected


@pytest.mark.parametrize(
    ("metadata", "interfaces", "match"),
    [
        (
            {"dnp3": {"interface": "eth9"}},
            [{"name": "eth0", "address": "10.0.0.1"}],
            "no addressed",
        ),
        ({"dnp3": []}, [{"name": "eth0"}], "no addressed"),
        ({"dnp3": []}, [], "no addressed"),
        (
            {"dnp3": {"interface": "eth0:http"}},
            [{"name": "eth0", "address": "10.0.0.1"}],
            "invalid dnp3 interface: invalid port",
        ),
    ],
)
def test_resolve_endpoint_names_host_on_failure(metadata, interfaces, match):
    with pytest.raises(ValueError, match=f"'rtu' .*{match}"):
        resolve_endpoint(node("rtu", metadata, interfaces), "dnp3", 20000)


def test_modbus_uses_shared_endpoint_resolution():
    client = Modbus()
    client.init_xml_root("client", node("ied", {"modbus": {"interface": "eth0:5020"}}))
    assert client.root.find("endpoint").text == "10.0.0.3:5020"


# --- Outstations -------------------------------------------------------------


def scenario(hosts, metadata=None):
    app = Box({"name": "ot-sim", "metadata": metadata or {}, "hosts": []})
    topology = {}
    for name, md, *rest in hosts:
        app.hosts.append({"hostname": name, "metadata": md})
        interfaces = (
            rest[0]
            if rest
            else [{"name": "eth0", "address": f"10.0.0.{len(topology) + 1}"}]
        )
        topology[name] = Box(
            {"general": {"hostname": name}, "network": {"interfaces": interfaces}}
        )
    return Outstations(app, topology.get)


CAP_VARS = ["voltage", "current", "freq", "power", "setpt"]
BRK_VARS = ["voltage", "current", "freq", "power", "status", "controls"]


def summary(points):
    return [(p.kind, p.index, p.device, p.variable) for p in points]


def test_fd_server_points_follow_infrastructure_order():
    rtus = scenario(
        [
            (
                "ied",
                {"type": "fd-server", "dnp3": [{"name": "cap1", "type": "capacitor"}]},
            )
        ]
    )
    points = rtus.points("ied")
    assert summary(points) == [
        ("ai", 0, "cap1", "voltage"),
        ("ai", 1, "cap1", "current"),
        ("ai", 2, "cap1", "freq"),
        ("ai", 3, "cap1", "power"),
        ("ao", 0, "cap1", "setpt"),
    ]
    assert points[0] == OutstationPoint(
        kind="ai",
        index=0,
        tag="cap1.voltage",
        device="cap1",
        device_type="capacitor",
        variable="voltage",
        register_type="analog-read",
        protocol="dnp3",
    )
    assert not points[0].writable
    assert points[0].analog
    assert points[4].writable
    assert points[4].analog


def test_fep_concatenates_upstreams_in_order_with_fresh_counters():
    rtus = scenario(
        [
            ("rtu", {"type": "fep", "upstream": ["brk-ied", "cap-ied"]}),
            (
                "cap-ied",
                {
                    "type": "fd-server",
                    "dnp3": [{"name": "opendss/cap1", "type": "capacitor"}],
                },
            ),
            (
                "brk-ied",
                {
                    "type": "fd-server",
                    "dnp3": {
                        "interface": "eth0",
                        "devices": [{"name": "671692", "type": "breaker"}],
                    },
                },
            ),
        ]
    )
    points = rtus.points("rtu")
    assert [(p.kind, p.index, p.device) for p in points if p.kind == "ai"] == [
        ("ai", i, "671692") for i in range(4)
    ] + [("ai", i, "cap1") for i in range(4, 8)]
    assert [
        (p.kind, p.index, p.variable) for p in points if p.kind in ("bi", "bo", "ao")
    ] == [
        ("bi", 0, "status"),
        ("bo", 0, "controls"),
        ("ao", 0, "setpt"),
    ]
    # the upstream IEDs are outstations too and number from zero themselves
    assert summary(rtus.points("cap-ied"))[0] == ("ai", 0, "cap1", "voltage")


def test_fep_legacy_connected_rtus_and_fep_chains():
    rtus = scenario(
        [
            ("top", {"type": "fep", "upstream": ["mid"]}),
            ("mid", {"type": "fep", "connected_rtus": ["ied"]}),
            (
                "ied",
                {"type": "fd-server", "dnp3": [{"name": "cap1", "type": "capacitor"}]},
            ),
        ]
    )
    assert summary(rtus.points("top")) == summary(rtus.points("mid"))
    assert len(rtus.points("top")) == 5


def test_fep_serves_modbus_registers_grouped_after_dnp3():
    rtus = scenario(
        [
            ("rtu", {"type": "fep", "upstream": ["mb-ied", "dnp-ied"]}),
            (
                "mb-ied",
                {"type": "fd-server", "modbus": [{"name": "load1", "type": "load"}]},
            ),
            (
                "dnp-ied",
                {"type": "fd-server", "dnp3": [{"name": "cap1", "type": "capacitor"}]},
            ),
        ]
    )
    points = rtus.points("rtu")
    assert [(p.protocol, p.device) for p in points if p.kind == "ai"] == [
        ("modbus", "load1")
    ] * 4 + [("dnp3", "cap1")] * 4


def test_duplicate_points_keep_their_real_addresses():
    rtus = scenario(
        [
            ("rtu", {"type": "fep", "upstream": ["ied", "ied"]}),
            (
                "ied",
                {"type": "fd-server", "dnp3": [{"name": "cap1", "type": "capacitor"}]},
            ),
        ]
    )
    points = [p for p in rtus.points("rtu") if p.variable == "setpt"]
    assert [(p.kind, p.index) for p in points] == [("ao", 0), ("ao", 1)]


def test_custom_infrastructure_mapping_and_per_host_infrastructure():
    metadata = {
        "infrastructure": "power-3-phase-distribution",
        "infrastructures": {
            "custom": {
                "pump": {
                    "flow": "analog-read",
                    "run": {"type": "binary-read-write", "dnp3": {"sbo": True}},
                }
            }
        },
    }
    rtus = scenario(
        [
            (
                "pump-ied",
                {
                    "type": "fd-server",
                    "infrastructure": "custom",
                    "dnp3": [{"name": "p1", "type": "pump"}],
                },
            ),
            (
                "node-ied",
                {"type": "fd-server", "dnp3": [{"name": "n1", "type": "node"}]},
            ),
        ],
        metadata,
    )
    assert summary(rtus.points("pump-ied")) == [
        ("ai", 0, "p1", "flow"),
        ("bo", 0, "p1", "run"),
    ]
    # hosts without their own infrastructure fall back to the app-level one
    assert [p.variable for p in rtus.points("node-ied")] == [
        "Va-mag",
        "Vb-mag",
        "Vc-mag",
        "Va-ang",
        "Vb-ang",
        "Vc-ang",
    ]


def test_empty_dnp3_section_has_no_points():
    rtus = scenario([("ied", {"type": "fd-server", "dnp3": []})])
    assert rtus.points("ied") == []


@pytest.mark.parametrize(
    ("hosts", "hostname", "match"),
    [
        (
            [("hmi", {"type": "fd-client", "connected_rtus": []})],
            "hmi",
            "type 'fd-client', not a DNP3 outstation",
        ),
        ([("ied", {"type": "fd-server", "modbus": []})], "ied", "has no dnp3 section"),
        (
            [("rtu", {"type": "fep", "downstream": "modbus"})],
            "rtu",
            "serves \\['modbus'\\] downstream",
        ),
        (
            [("ied", {"type": "fd-server", "dnp3": {"interface": "eth0"}})],
            "ied",
            "'ied' has invalid device metadata: (Box)?KeyError",
        ),
        (
            [
                (
                    "ied",
                    {"type": "fd-server", "dnp3": [{"name": "x", "type": "spaceship"}]},
                )
            ],
            "ied",
            "'ied' has invalid device metadata: AssertionError",
        ),
        (
            [("rtu", {"type": "fep", "upstream": ["ghost"]})],
            "rtu",
            "'rtu' has invalid device metadata: KeyError: 'ghost'",
        ),
        (
            [
                ("a", {"type": "fep", "upstream": ["b"]}),
                ("b", {"type": "fep", "upstream": ["a"]}),
            ],
            "a",
            "RecursionError",
        ),
    ],
)
def test_invalid_outstations_raise_named_errors(hosts, hostname, match):
    with pytest.raises(ValueError, match=match):
        scenario(hosts).points(hostname)


def test_unknown_and_missing_hosts():
    rtus = scenario([("ied", {"type": "fd-server", "dnp3": []})])
    assert "ied" in rtus
    assert "other" not in rtus
    with pytest.raises(ValueError, match="'other' is not an ot-sim host"):
        rtus.points("other")
    with pytest.raises(ValueError, match="'other' is not an ot-sim host"):
        rtus.endpoint("other")
    assert "ied" not in Outstations(None, lambda hostname: None)


def test_hosts_without_topology_nodes_are_ignored():
    app = Box(
        {
            "name": "ot-sim",
            "hosts": [{"hostname": "ied", "metadata": {"type": "fd-server"}}],
        }
    )
    assert "ied" not in Outstations(app, lambda hostname: None)


def test_endpoint_uses_the_dnp3_interface_setting():
    rtus = scenario(
        [
            (
                "rtu",
                {
                    "type": "fep",
                    "upstream": ["ied"],
                    "dnp3": {"interface": "eth1:20001"},
                },
                [
                    {"name": "eth0", "address": "10.0.0.1"},
                    {"name": "eth1", "address": "10.0.0.2"},
                ],
            ),
            ("ied", {"type": "fd-server", "dnp3": []}),
        ]
    )
    assert rtus.endpoint("rtu") == ("10.0.0.2", 20001)
    assert rtus.endpoint("ied") == ("10.0.0.2", 20000)
