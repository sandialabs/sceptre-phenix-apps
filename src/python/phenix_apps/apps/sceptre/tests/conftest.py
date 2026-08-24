"""Shared fixtures and node builders for the sceptre app tests.

The `mock_app` fixture and the `app_class` marker come from the
phenix_apps.testing pytest plugin, which loads automatically via the
pytest11 entry point -- see phenix_apps/testing/README.md.
"""

import io
import logging
import pathlib

import pytest
from box import Box
from loguru import logger

from phenix_apps.apps.sceptre.configs.registers import Register


@pytest.fixture(autouse=True)
def caplog_loguru_sink(caplog):  # noqa: ARG001
    """Route loguru records into stdlib logging so caplog can see them.

    Same shim as phenix_apps/apps/scale/conftest.py; the app logs through
    loguru, which does not propagate to caplog on its own.
    """

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield
    logger.remove(handler_id)


@pytest.fixture(autouse=True)
def _reset_register_addresses():
    """Register.addresses is class-level mutable state.

    FieldDeviceConfig.__generate_protocols resets it after building each config,
    but a test that raises part-way through leaves it dirty for the next test.
    """
    Register.reset_addresses()
    yield
    Register.reset_addresses()


@pytest.fixture
def sceptre_app(mock_app, mocker, tmp_path):
    """A mocked Sceptre with the directories __init__ would have created.

    mock_app patches __init__ out, so the app-specific attributes are unset, and
    it only mocks methods defined on AppBase -- Sceptre's own helpers have to be
    mocked here. Tests that want the real find_override call it unbound:
    Sceptre.find_override(app, ...).
    """
    mock_app.find_override = mocker.MagicMock(return_value=None)
    mock_app.render_sceptre_start = mocker.MagicMock()
    mock_app._used_overrides = set()
    mock_app.startup_dir = tmp_path / "startup"
    mock_app.sceptre_dir = tmp_path / "sceptre"
    mock_app.elk_dir = tmp_path / "elk"
    for path in (mock_app.startup_dir, mock_app.sceptre_dir, mock_app.elk_dir):
        path.mkdir(parents=True, exist_ok=True)
    return mock_app


def node(hostname, metadata=None, os_type="linux", interfaces=()):
    """Build a host Box shaped like what AppBase.extract_nodes_* returns.

    The handlers read both halves of this shape: `metadata` is the host entry
    from the scenario app, `topology` is the matching topology node that
    extract_nodes_* merges in.

    Args:
        hostname: Host name, used for both the app host and the topology node.
        metadata: The scenario "metadata" mapping, e.g. {"type": "fd-server"}.
        os_type: "linux" or "windows"; several handlers branch on it.
        interfaces: Interface dicts, most easily built with `iface`.
    """
    return Box(
        {
            "hostname": hostname,
            "metadata": metadata or {},
            "topology": {
                "general": {"hostname": hostname},
                "hardware": {"os_type": os_type},
                "network": {"interfaces": list(interfaces)},
            },
        }
    )


def iface(name, address, vlan="field", kind="ethernet", **extra):
    """Build one network interface dict for `node`.

    Args:
        name: Interface name. The fep handler looks for "upstream" in it.
        address: IPv4 address.
        vlan: VLAN name. Note the app filters mgmt interfaces case-sensitively
            in some blocks and case-insensitively in others, so "mgmt" and
            "MGMT" are not interchangeable here.
        kind: Interface type, "ethernet" or "serial". Named `kind` because
            `type` shadows the builtin.
        **extra: Extra keys merged in last, e.g. device="/dev/ttyS0".
    """

    return {"name": name, "address": address, "vlan": vlan, "type": kind, **extra}


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    """Build a real Sceptre from the golden fixture, optionally mutated first.

    Unlike `sceptre_app` this is not mocked -- it parses the same YAML the
    golden test uses, so validation runs against a realistic whole scenario
    rather than a hand-built host. The returned callable takes a function that
    edits the parsed Box in place.

    Usage:
        app = scenario(lambda exp: host(exp, "rtu-1").metadata.pop("provider"))
    """

    from phenix_apps.apps.sceptre.app import Sceptre

    fixture = pathlib.Path(__file__).parent / "test_sceptre_input.yaml"

    def build(mutate=None):
        exp = Box.from_yaml(fixture.read_text())
        exp.spec.baseDir = str(tmp_path / "exp")
        if mutate:
            mutate(exp)
        monkeypatch.setattr("sys.stdin", io.StringIO(exp.to_json()))
        return Sceptre("sceptre", "configure")

    return build


def host(exp, hostname):
    """Return a host entry from the sceptre app's host list."""

    return next(h for h in exp.spec.scenario.apps[0].hosts if h.hostname == hostname)


def topo_node(exp, hostname):
    """Return a topology node by hostname."""

    return next(n for n in exp.spec.topology.nodes if n.general.hostname == hostname)


def drop_topo_node(exp, hostname):
    """Remove a topology node, leaving the scenario host entry dangling."""

    exp.spec.topology.nodes = [
        n for n in exp.spec.topology.nodes if n.general.hostname != hostname
    ]


def only_mgmt_interface(exp, hostname):
    """Strip a host down to its first interface, which is mgmt in the fixture."""

    node = topo_node(exp, hostname)
    node.network.interfaces = [node.network.interfaces[0]]
