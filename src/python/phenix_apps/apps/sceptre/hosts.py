"""Topology questions both stages ask.

Reads with getattr, so one helper takes all three shapes a host arrives in: the
merged host, the bare topology node, and the validation model.
"""

import re
from typing import Any


def interfaces(host: Any) -> list[Any]:
    """A host's network interfaces, or [] if it has no topology node."""

    topology = getattr(host, "topology", None) or host
    network = getattr(topology, "network", None)
    if not network:
        return []
    return list(getattr(network, "interfaces", []) or [])


def address(host: Any) -> str:
    """The address a host is reached at. IndexError if it has none."""

    return interfaces(host)[0].address


def os_type(host: Any) -> str:
    """A host's OS, "linux" or "windows"."""

    topology = getattr(host, "topology", None) or host
    return getattr(getattr(topology, "hardware", None), "os_type", "")


def is_backup(hostname: str) -> bool:
    """Whether the app treats this host as a backup, by name alone."""

    return bool(re.search(r"secondary|bak", hostname))


def vlan_of(iface: Any) -> str:
    """An interface's vlan, or "" when it declares none."""

    return getattr(iface, "vlan", "") or ""


def non_mgmt(host: Any, *, case_sensitive: bool = True) -> list[Any]:
    """Interfaces the app treats as non-management.

    OPC/SCADA/historian compare exactly, field devices lowercase first; callers
    pass what their handler uses. See "Known issues" in the README.
    """

    def is_mgmt(iface: Any) -> bool:
        vlan = vlan_of(iface)
        if not case_sensitive:
            vlan = vlan.lower()
        return vlan == "mgmt"

    return [iface for iface in interfaces(host) if not is_mgmt(iface)]


def mgmt(host: Any) -> list[Any]:
    """Interfaces on the mgmt vlan, matched case-insensitively."""

    return [iface for iface in interfaces(host) if vlan_of(iface).lower() == "mgmt"]


def describe_interfaces(host: Any) -> str:
    """Human-readable interface list, for use as a validation hint.

    e.g. "interfaces: IF0 (vlan mgmt), IF1 (vlan unset)"
    """

    found = interfaces(host)
    if not found:
        return "this host has no interfaces at all"

    descriptions = []
    for iface in found:
        name = getattr(iface, "name", None) or "?"
        vlan = vlan_of(iface) or "unset"
        descriptions.append(f"{name} (vlan {vlan})")

    return "interfaces: " + ", ".join(descriptions)


def same_subnet(one: str, other: str) -> bool:
    """Whether two addresses share their first three octets: a /24 assumption."""

    return one.split(".")[:-1] == other.split(".")[:-1]
