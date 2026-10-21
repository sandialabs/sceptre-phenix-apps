import re
import warnings
from typing import cast

import minimega
from box import Box

from phenix_apps.common import utils


class ExperimentBase:
    """
    Experiment lookups and the minimega connection shared by AppBase and
    ComponentBase. Subclasses set ``experiment`` and ``exp_name``.
    """

    experiment: Box
    exp_name: str

    @property
    def mm(self) -> minimega.minimega:
        """
        minimega instance that's initialized the first time it's referenced.
        """
        if not getattr(self, "_mm", None):
            self._mm = self.mm_init()
        return self._mm

    @mm.setter
    def mm(self, mm_obj: minimega.minimega) -> None:
        self._mm = mm_obj

    def mm_init(self, namespaced: bool = True) -> minimega.minimega:
        """Connect to minimega, in this experiment's namespace by default."""

        return utils._mm_init(self.exp_name if namespaced else None)

    def extract_node(
        self, hostname: str, wildcard: bool = False
    ) -> Box | list[Box] | None:
        if wildcard:
            regex = re.compile(hostname)

            return [
                node
                for node in self.experiment.spec.topology.nodes
                if regex.match(node.general.hostname)
            ]

        for node in self.experiment.spec.topology.nodes:
            if node.general.hostname == hostname:
                return node

        return None

    def require_node(self, hostname: str) -> Box:
        """extract_node for one hostname, raising ValueError if it is missing."""

        node = self.extract_node(hostname)
        if not node:
            raise ValueError(f"node {hostname} does not exist")
        return cast(Box, node)

    def get_annotation(self, key: str) -> str | None:
        metadata = self.experiment.get("metadata")
        if metadata and "annotations" in metadata:
            return metadata.annotations.get(key)

        return None

    def extract_node_names(self) -> list[str]:
        return [node.general.hostname for node in self.experiment.spec.topology.nodes]

    def extract_node_os_type(self, name: str) -> str:
        """
        A node's os_type, lowercased. An unset os_type is "linux", as phenix
        core defaults it, except on external nodes, which core leaves unset.
        """

        node = self.require_node(name)
        os_type = (node.get("hardware") or {}).get("os_type") or ""
        if not os_type and not node.get("external"):
            os_type = "linux"
        return os_type.lower()

    @staticmethod
    def _node_interface(node: Box, iface: str | int | None) -> Box | None:
        """The interface named iface, at index iface, or the first one if unset."""

        interfaces = (node.get("network") or {}).get("interfaces") or []

        if iface is None or iface == "":
            return interfaces[0] if interfaces else None
        if isinstance(iface, int):
            return interfaces[iface] if 0 <= iface < len(interfaces) else None

        return next((i for i in interfaces if i.get("name") == iface), None)

    def extract_node_ip(self, name: str, iface: str | int | None = None) -> str:
        """
        Return the address of a node's interface, chosen by name, by index, or
        the first interface when iface is unset. Raises ValueError naming the
        node and interface when either is missing or the interface has no
        address.
        """

        node = self.require_node(name)
        interface = self._node_interface(node, iface)
        if interface is None:
            if iface is None or iface == "":
                raise ValueError(f"node {name} has no interfaces")
            raise ValueError(f"interface {iface} does not exist on node {name}")

        if not interface.get("address"):
            raise ValueError(
                f"interface {interface.get('name', iface)} on node {name} has no address"
            )

        return interface["address"]

    def extract_node_interface_ip(
        self, hostname: str, iface: str, include_mask: bool = False
    ) -> str | tuple[str, int] | None:
        """DEPRECATED -- use :meth:`extract_node_ip`, which raises an error naming
        the node and interface instead of returning None.

        Returns the address of the named interface, or the first interface if
        iface is empty, or None. With include_mask, returns (address, mask).
        """
        warnings.warn(
            "extract_node_interface_ip is deprecated. "
            "Use extract_node_ip, which raises instead of returning None.",
            DeprecationWarning,
            stacklevel=2,
        )

        node = self.extract_node(hostname)
        interface = self._node_interface(cast(Box, node), iface) if node else None

        if not interface or "address" not in interface:
            return None
        if include_mask:
            return interface["address"], interface.get("mask")

        return interface["address"]

    def extract_node_hostname_for_ip(self, address: str) -> str | None:
        address, _ = utils.split_host_port(address)

        for node in self.experiment.spec.topology.nodes:
            for i in (node.get("network") or {}).get("interfaces") or []:
                if i.get("address") == address:
                    return node.general.hostname

        return None
