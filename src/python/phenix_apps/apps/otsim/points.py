"""Build-time view of the DNP3 points an ot-sim outstation serves.

Other apps (Ignition) use this to give the points of an ot-sim `fep` or
`fd-server` meaningful names: the numbering here is the one
`protocols.dnp3.assign_addresses` applies when the outstation config is
rendered, so both always agree.
"""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from box import Box

from phenix_apps.apps.otsim.device import FEP, FieldDeviceServer
from phenix_apps.apps.otsim.protocols.dnp3 import assign_addresses
from phenix_apps.apps.otsim.protocols.protocol import resolve_endpoint

OUTSTATION_TYPES = ("fd-server", "fep")
DNP3_PORT = 20000


@dataclass(frozen=True)
class OutstationPoint:
    """One DNP3 point and the infrastructure variable behind it."""

    kind: str  # ai, ao, bi, bo
    index: int
    tag: str  # ot-sim tag, e.g. `cap1.voltage`
    device: str
    device_type: str
    variable: str
    register_type: str
    protocol: str  # host metadata section the register came from

    @property
    def analog(self) -> bool:
        return self.kind in ("ai", "ao")

    @property
    def writable(self) -> bool:
        return self.kind in ("ao", "bo")


class Outstations:
    """DNP3 outstations defined by an ot-sim app in a scenario.

    `otsim_app` is the app's scenario entry (`AppBase.extract_app("ot-sim")`)
    and `extract_node` resolves a hostname to its topology node. Devices are
    processed the way `OTSim.pre_start` does, lazily and once.
    """

    def __init__(self, otsim_app: Box | None, extract_node: Callable[[str], Any]):
        self._metadata = otsim_app.get("metadata", {}) if otsim_app else {}
        self._nodes: dict[str, Box] = {}
        self._devices: dict[str, Any] | None = None

        for host in otsim_app.get("hosts", []) if otsim_app else []:
            topology = extract_node(host.hostname)
            if topology is None:
                continue
            node = copy.deepcopy(host)
            node.update({"topology": topology})
            self._nodes[host.hostname] = node

    def __contains__(self, hostname: str) -> bool:
        return hostname in self._nodes

    def _type(self, hostname: str) -> str | None:
        return self._nodes[hostname].metadata.get("type")

    def _build(self) -> dict[str, Any]:
        if self._devices is not None:
            return self._devices

        mappings = self._metadata.get("infrastructures", {})
        default_infra = self._metadata.get("infrastructure", "power-distribution")
        devices: dict[str, Any] = {}

        for hostname, node in self._nodes.items():
            if self._type(hostname) == "fd-server":
                infra = node.metadata.get("infrastructure", default_infra)
                devices[hostname] = self._process(
                    hostname, FieldDeviceServer(node, infra), mappings
                )
        for hostname, node in self._nodes.items():
            if self._type(hostname) == "fep":
                devices[hostname] = FEP(node)
        for hostname in list(devices):
            device = devices[hostname]
            if isinstance(device, FEP):
                self._process(hostname, device, devices)

        self._devices = devices
        return devices

    @staticmethod
    def _process(hostname: str, device: Any, arg: Any) -> Any:
        """Run the ot-sim register processing, naming the host on failure."""
        try:
            device.process(arg)
        except (KeyError, AssertionError, RecursionError, TypeError) as exc:
            raise ValueError(
                f"ot-sim host '{hostname}' has invalid device metadata: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return device

    def points(self, hostname: str) -> list[OutstationPoint]:
        """The points `hostname`'s DNP3 outstation serves, in address order.

        Raises `ValueError` when the host is not a DNP3 outstation.
        """
        if hostname not in self._nodes:
            raise ValueError(f"'{hostname}' is not an ot-sim host")

        kind = self._type(hostname)
        if kind not in OUTSTATION_TYPES:
            raise ValueError(
                f"ot-sim host '{hostname}' is type '{kind}', not a DNP3 outstation "
                f"({' or '.join(OUTSTATION_TYPES)})"
            )

        device = self._build()[hostname]
        md = self._nodes[hostname].metadata

        if kind == "fd-server":
            if "dnp3" not in md:
                raise ValueError(f"ot-sim host '{hostname}' has no dnp3 section")
            registers = device.registers.get("dnp3", [])
        else:
            downstream = md.get("downstream", [])
            if not isinstance(downstream, list):
                downstream = [downstream]
            if downstream and "dnp3" not in downstream:
                raise ValueError(
                    f"ot-sim fep '{hostname}' serves {downstream} downstream, not dnp3"
                )
            # the fep outstation serves every upstream register, grouped by the
            # protocol it was collected from
            registers = [reg for regs in device.registers.values() for reg in regs]

        return [
            OutstationPoint(
                kind=point_kind,
                index=index,
                tag=reg.tag,
                device=reg.device,
                device_type=reg.device_type,
                variable=reg.variable,
                register_type=reg.type,
                protocol=reg.protocol,
            )
            for point_kind, index, reg in assign_addresses(registers)
        ]

    def endpoint(self, hostname: str) -> tuple[str, int]:
        """The `(ip, port)` the host's DNP3 outstation listens on."""
        if hostname not in self._nodes:
            raise ValueError(f"'{hostname}' is not an ot-sim host")
        return resolve_endpoint(self._nodes[hostname], "dnp3", DNP3_PORT)
