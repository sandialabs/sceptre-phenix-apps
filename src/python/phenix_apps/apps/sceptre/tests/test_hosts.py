"""Tests for the topology helpers both stages share."""

import pytest

from phenix_apps.apps.sceptre import hosts, validation
from phenix_apps.apps.sceptre.tests.conftest import iface, node


def test_a_host_with_no_topology_node_has_no_interfaces():
    bare = node("rtu-1")
    del bare["topology"]

    assert hosts.interfaces(bare) == []


class TestNonMgmt:
    """The case-sensitivity split is a documented bug, so it is pinned here."""

    @pytest.mark.parametrize(
        ("vlan", "case_sensitive", "kept"),
        [
            ("mgmt", True, False),
            ("mgmt", False, False),
            ("MGMT", True, True),  # the phenix convention, kept by this branch
            ("MGMT", False, False),
            ("field", True, True),
        ],
    )
    def test_vlan_matching(self, vlan, case_sensitive, kept):
        host = node("rtu-1", interfaces=[iface("IF0", "10.0.0.1", vlan=vlan)])

        found = hosts.non_mgmt(host, case_sensitive=case_sensitive)

        assert bool(found) is kept

    def test_an_interface_with_no_vlan_is_not_mgmt(self):
        host = node("rtu-1", interfaces=[{"name": "IF0", "address": "10.0.0.1"}])

        assert len(hosts.non_mgmt(host)) == 1

    def test_mgmt_matches_case_insensitively(self):
        host = node(
            "rtu-1",
            interfaces=[
                iface("IF0", "172.16.0.1", vlan="MGMT"),
                iface("IF1", "10.0.0.1"),
            ],
        )

        assert [i.address for i in hosts.mgmt(host)] == ["172.16.0.1"]


def test_works_on_a_bare_topology_node():
    """extract_node() returns the node itself, not a host with one merged in.

    The fd-server handler passes exactly that when metadata.server_hostname
    names another host.
    """

    host = node("srv-1", interfaces=[iface("IF0", "10.9.0.9")])

    assert hosts.address(host.topology) == "10.9.0.9"
    assert hosts.os_type(host.topology) == "linux"


def test_works_on_the_validation_model_too():
    """The premise of the module: one helper for the Box and the model."""

    box = node(
        "rtu-1",
        interfaces=[iface("IF0", "172.16.0.1", vlan="mgmt"), iface("IF1", "10.0.0.1")],
    )
    model = validation.Host.model_validate(
        {"hostname": box.hostname, "topology": box.topology.to_dict()},
        context={"problems": [], "hostnames": set()},
    )

    assert [i.address for i in hosts.non_mgmt(box)] == ["10.0.0.1"]
    assert [i.address for i in hosts.non_mgmt(model)] == ["10.0.0.1"]
    assert hosts.describe_interfaces(box) == hosts.describe_interfaces(model)


@pytest.mark.parametrize(
    ("one", "other", "expected"),
    [
        ("10.2.0.11", "10.2.0.30", True),
        ("10.2.0.11", "10.3.0.30", False),
        ("172.16.0.1", "172.16.0.255", True),
    ],
)
def test_same_subnet_compares_the_first_three_octets(one, other, expected):
    assert hosts.same_subnet(one, other) is expected
