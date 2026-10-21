"""Broker lookup failures keep their role context."""

from types import SimpleNamespace

import pytest

from phenix_apps.apps.helics.app import Helics


def make_app(broker_md, federates=()):
    app = object.__new__(Helics)
    app.name = "helics"
    app.metadata = {"broker": broker_md}

    def extract_node_ip(host, iface):
        if host == "missinghost":
            raise ValueError(f"node {host} not found")
        return "10.0.0.1"

    app.extract_node_ip = extract_node_ip
    app.extract_node_hostname_for_ip = lambda ip: "root"
    app.is_booting = lambda host: True
    app.add_label = lambda *a, **k: None
    app.add_inject = lambda *a, **k: None
    app.extract_annotated_topology_nodes = lambda key: list(federates)
    return app


def test_root_broker_not_found():
    app = make_app({"root": "missinghost|eth0"})
    with pytest.raises(ValueError, match="root broker not found in topology"):
        app.pre_start()


def test_sub_broker_not_found(tmp_path):
    fed = SimpleNamespace(
        general=SimpleNamespace(hostname="fed1"),
        annotations={"helics/federate": [{"broker": "missinghost|eth0"}]},
    )
    app = make_app({"root": "10.0.0.1"}, [fed])
    app.helics_dir = tmp_path
    with pytest.raises(ValueError, match=r"^broker not found in topology"):
        app.pre_start()
