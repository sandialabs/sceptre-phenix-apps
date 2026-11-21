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


def sub_broker_app(tmp_path, brokers):
    """A root on 10.0.0.1 and one federate node per annotation broker in `brokers`."""

    feds = [
        SimpleNamespace(
            general=SimpleNamespace(hostname=f"fed{i}"),
            annotations={"helics/federate": [{"broker": broker, "fed-count": 1}]},
        )
        for i, broker in enumerate(brokers)
    ]
    app = make_app({"root": "10.0.0.1"}, feds)
    app.helics_dir = tmp_path
    ips = {"root": "10.0.0.1", "sub": "10.0.0.2"}
    app.extract_node_ip = lambda host, iface: ips[host]
    app.extract_node_hostname_for_ip = lambda ip: {v: k for k, v in ips.items()}.get(
        ip.split(":")[0]
    )
    return app


@pytest.mark.parametrize(
    "broker",
    ["10.0.0.2", "sub|IF0", "10.0.0.2:24000"],
    ids=["ip", "host-iface", "ip-port"],
)
def test_sub_broker_from_each_annotation_form(tmp_path, broker):
    """The README's forms: an address without a port, hostname|iface, or ip:port."""

    sub_broker_app(tmp_path, [broker]).pre_start()

    script = (tmp_path / "sub-broker.sh").read_text()
    assert "--broker 10.0.0.1 --local_interface 10.0.0.2:24000" in script
    assert "-f1 " in script
    assert "--subbrokers 1 " in (tmp_path / "root-broker.sh").read_text()


def test_sub_broker_counts_every_federate_in_any_form(tmp_path):
    sub_broker_app(tmp_path, ["10.0.0.2", "sub|IF0", "10.0.0.2:24000"]).pre_start()

    script = (tmp_path / "sub-broker.sh").read_text()
    assert script.count("helics_broker") == 1
    assert "-f3 " in script


def test_two_sub_broker_endpoints_on_one_host(tmp_path):
    sub_broker_app(tmp_path, ["10.0.0.2:24000", "10.0.0.2:24001"]).pre_start()

    script = (tmp_path / "sub-broker.sh").read_text()
    assert script.count("helics_broker") == 2
    assert "--local_interface 10.0.0.2:24001" in script
    assert "--subbrokers 2 " in (tmp_path / "root-broker.sh").read_text()
