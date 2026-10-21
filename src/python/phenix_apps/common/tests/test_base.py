from types import SimpleNamespace

import pytest
from box import Box

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.common import settings
from phenix_apps.common.base import ExperimentBase


@pytest.mark.parametrize(
    ("namespaced", "expected"),
    [
        (True, {"path": "/custom/minimega", "namespace": "exp"}),
        (False, {"path": "/custom/minimega"}),
    ],
)
def test_mm_init_uses_the_configured_socket(monkeypatch, namespaced, expected):
    calls = []
    monkeypatch.setattr(settings, "MM_SOCKET_PATH", "/custom/minimega")
    monkeypatch.setattr("minimega.connect", lambda **kwargs: calls.append(kwargs))

    ComponentBase.mm_init(SimpleNamespace(exp_name="exp"), namespaced=namespaced)

    assert calls == [expected]


def _node(hostname, *interfaces):
    return {
        "general": {"hostname": hostname},
        "network": {"interfaces": list(interfaces)},
    }


class _Exp(ExperimentBase):
    def __init__(self):
        self.exp_name = "exp"
        self.experiment = Box(
            {
                "spec": {
                    "topology": {
                        "nodes": [
                            _node(
                                "plc-1",
                                {"name": "eth0", "address": "10.0.0.1", "mask": 24},
                                {"name": "eth1", "address": "fe80::1", "mask": 64},
                                {"name": "eth2"},
                            ),
                            _node("plc-2", {"name": "eth0", "address": "10.0.0.2"}),
                            _node("bare"),
                        ]
                    }
                }
            }
        )


@pytest.fixture
def exp():
    return _Exp()


def test_extract_node_and_names(exp):
    assert exp.extract_node("plc-2").general.hostname == "plc-2"
    assert exp.extract_node("nope") is None
    assert [n.general.hostname for n in exp.extract_node("plc-.", wildcard=True)] == [
        "plc-1",
        "plc-2",
    ]
    assert exp.extract_node_names() == ["plc-1", "plc-2", "bare"]


@pytest.mark.parametrize(
    ("iface", "expected"),
    [(None, "10.0.0.1"), ("", "10.0.0.1"), ("eth1", "fe80::1"), (1, "fe80::1")],
)
def test_extract_node_ip(exp, iface, expected):
    assert exp.extract_node_ip("plc-1", iface) == expected


def test_extract_node_ip_keeps_the_name_keyword(exp):
    assert exp.extract_node_ip(name="plc-2", iface="eth0") == "10.0.0.2"


@pytest.mark.parametrize(
    ("name", "iface", "error"),
    [
        ("nope", "eth0", "node nope does not exist"),
        ("plc-1", "eth9", "interface eth9 does not exist on node plc-1"),
        ("plc-1", 7, "interface 7 does not exist on node plc-1"),
        ("plc-1", "eth2", "interface eth2 on node plc-1 has no address"),
        ("bare", None, "node bare has no interfaces"),
    ],
)
def test_extract_node_ip_errors_name_the_node_and_interface(exp, name, iface, error):
    with pytest.raises(ValueError, match=error):
        exp.extract_node_ip(name, iface)


@pytest.mark.parametrize(
    ("hostname", "iface", "include_mask", "expected"),
    [
        ("plc-1", "eth1", False, "fe80::1"),
        ("plc-1", "", False, "10.0.0.1"),
        ("plc-1", "eth0", True, ("10.0.0.1", 24)),
        ("plc-1", "eth2", False, None),
        ("plc-1", "eth9", False, None),
        ("bare", "", False, None),
        ("nope", "eth0", False, None),
    ],
)
def test_extract_node_interface_ip_keeps_its_legacy_contract(
    exp, hostname, iface, include_mask, expected
):
    with pytest.deprecated_call():
        assert exp.extract_node_interface_ip(hostname, iface, include_mask) == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("10.0.0.2", "plc-2"),
        ("10.0.0.2:502", "plc-2"),
        ("fe80::1", "plc-1"),
        ("[fe80::1]:20000", "plc-1"),
        ("10.9.9.9", None),
    ],
)
def test_extract_node_hostname_for_ip(exp, address, expected):
    assert exp.extract_node_hostname_for_ip(address) == expected


def test_mm_connects_once_and_can_be_replaced(exp, monkeypatch):
    connects = []
    monkeypatch.setattr(
        "phenix_apps.common.utils._mm_init",
        lambda namespace: connects.append(namespace) or object(),
    )

    first = exp.mm

    assert exp.mm is first
    assert connects == ["exp"]

    exp.mm = "replacement"
    assert exp.mm == "replacement"


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"hardware": {"os_type": "Windows"}}, "windows"),
        ({"hardware": {"os_type": "linux"}}, "linux"),
        # phenix core defaults an unset os_type to linux, except on external nodes
        ({"hardware": {}}, "linux"),
        ({}, "linux"),
        ({"external": True}, ""),
    ],
)
def test_extract_node_os_type(exp, node, expected):
    exp.experiment.spec.topology.nodes.append({"general": {"hostname": "n"}, **node})

    assert exp.extract_node_os_type("n") == expected


def test_extract_node_os_type_names_a_missing_node(exp):
    with pytest.raises(ValueError, match="node nope does not exist"):
        exp.extract_node_os_type("nope")


@pytest.mark.parametrize(
    "metadata",
    [None, Box({}), Box({"elasticsearch": None}), Box({"elasticsearch": {}})],
)
def test_es_names_a_missing_server(metadata):
    component = SimpleNamespace(_es=None, metadata=metadata, name="c")

    with pytest.raises(ValueError, match=r"'c': metadata.elasticsearch.server"):
        ComponentBase.es.fget(component)


def test_require_node_names_a_missing_node(exp):
    assert exp.require_node("plc-2").general.hostname == "plc-2"

    with pytest.raises(ValueError, match="node nope does not exist"):
        exp.require_node("nope")


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"annotations": {"topology": "topo"}}, "topo"),
        ({"annotations": {}}, None),
        ({}, None),
        (None, None),
    ],
)
def test_get_annotation(exp, metadata, expected):
    if metadata is not None:
        exp.experiment.metadata = metadata

    assert exp.get_annotation("topology") == expected


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (None, "1"),
        ({}, "1"),
        ({"runs": [{}, {"name": "b"}]}, "b"),
        ({"runs": [{}]}, "1"),
    ],
)
def test_extract_run_name(metadata, expected):
    scorch = Box({"name": "scorch", "metadata": metadata}, box_none_transform=False)
    component = SimpleNamespace(run=1, extract_app=lambda name: scorch)

    assert ComponentBase.extract_run_name(component) == expected


def test_lookups_skip_a_node_with_null_network(exp):
    # phenix core accepts a node whose network is null
    exp.experiment.spec.topology.nodes.append(
        {"general": {"hostname": "ext"}, "network": None}
    )

    assert exp.extract_node_hostname_for_ip("10.0.0.2") == "plc-2"
    # an unmapped address makes the lookup traverse the null-network node
    assert exp.extract_node_hostname_for_ip("10.9.9.9") is None
    with pytest.raises(ValueError, match="node ext has no interfaces"):
        exp.extract_node_ip("ext")
