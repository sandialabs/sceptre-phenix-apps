"""The sceptre metadata vocabulary: simulators, infrastructures, device lists."""

import copy
from enum import StrEnum
from typing import ClassVar, Final

from box import Box

from phenix_apps.common import error
from phenix_apps.common.logger import logger

# Where a provider publishes state by default: UDP multicast, with the "*"
# replaced by the device's own mgmt address when it binds.
DEFAULT_PUBLISH_ENDPOINT: Final[str] = "udp://*;239.0.0.1:40000"

# The port a provider answers state queries on.
PROVIDER_PORT: Final[int] = 5555


def server_endpoint(ip: str) -> str:
    """Where a field device reaches its provider."""

    return f"tcp://{ip}:{PROVIDER_PORT}"


# The four field types a device exposes registers for, in generation order.
FIELD_TYPES: Final[tuple[str, ...]] = (
    "analog-read",
    "analog-read-write",
    "binary-read",
    "binary-read-write",
)

# What a device entry under a protocol key may carry: its identity, plus
# per-device register overrides that replace the infrastructure's defaults.
DEVICE_KEYS: Final[tuple[str, ...]] = ("type", "name", *FIELD_TYPES)


class Simulator(StrEnum):
    """Simulator names, as written in metadata.simulator.

    Case matters: the value reaches config.ini as `solver`, which bennu and the
    phenix schemas match on.
    """

    POWER_WORLD = "PowerWorld"
    POWER_WORLD_HELICS = "PowerWorldHelics"
    POWER_WORLD_DYNAMICS = "PowerWorldDynamics"
    PYPOWER = "PyPower"
    SIMULINK = "Simulink"
    GENERIC_PYTHON = "GenericPython"
    HELICS = "Helics"
    OPALRT = "OPALRT"
    RTDS = "RTDS"
    SIREN = "Siren"

    @classmethod
    def parse(cls, value: str) -> "Simulator | None":
        """Case-insensitive lookup for validation; None if unknown."""

        return next((s for s in cls if s.lower() == (value or "").lower()), None)


class Infrastructure(StrEnum):
    """Infrastructures, as written in metadata.infrastructure."""

    BATCH_PROCESS = "batch-process"
    BATTERY = "battery"
    FUEL = "fuel"
    GENERIC = "generic"
    HVAC = "hvac"
    OPALRT = "opalrt"
    POWER_DISTRIBUTION = "power-distribution"
    POWER_TRANSMISSION = "power-transmission"
    RTDS = "rtds"
    WATERWAY = "waterway"


class SceptreMetadataParser:
    """Pulls the per-protocol device lists out of a field device's metadata.

    ``dnp3: [{type: bus, name: bus-1}, ...]`` becomes devices_by_protocol, which
    the configs package turns into registers.
    """

    protocols: ClassVar[list[str]] = [
        "bacnet",
        "dnp3",
        "dnp3-serial",
        "modbus",
        "sunspec",
        "iec60870-5-104",
    ]

    def __init__(self, metadata: Box) -> None:
        """Parse one host's metadata. AppError if infrastructure or provider is missing."""

        try:
            self.infrastructure_name = metadata.infrastructure
            self.provider_name = metadata.provider
            self.devices_by_protocol = {}

            for protocol in self.protocols:
                if protocol in metadata:
                    # Keys outside DEVICE_KEYS are dropped rather than passed on
                    # as stray create_device kwargs; validation reports them.
                    self.devices_by_protocol[protocol] = [
                        {k: v for k, v in device.items() if k in DEVICE_KEYS}
                        for device in copy.deepcopy(metadata[protocol])
                    ]
        except Exception as e:
            msg = f"Failed when parsing metadata.\nError: {e}"
            logger.error(msg)
            raise error.AppError(msg) from None
