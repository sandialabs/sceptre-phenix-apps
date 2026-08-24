"""Builds one device from the table in infrastructures.yaml.

The table says which device types an infrastructure has and which fields each
exposes. A device entry may override any of those field lists.
"""

from pathlib import Path
from typing import Any, Final

import yaml

from phenix_apps.apps.sceptre.configs.registers import Device
from phenix_apps.apps.sceptre.metadata import FIELD_TYPES
from phenix_apps.common import error

TABLE: Final[Path] = Path(__file__).with_name("infrastructures.yaml")


def load_table(path: Path = TABLE) -> dict[str, Any]:
    """Read the table, with ranges as tuples the way the app has them."""

    table = yaml.safe_load(path.read_text())

    for infrastructure in table.values():
        infrastructure["range"] = tuple(infrastructure["range"])
        for device in infrastructure["devices"].values():
            if "range" in device:
                device["range"] = tuple(device["range"])

    return table


INFRASTRUCTURES: Final[dict[str, Any]] = load_table()


class Infrastructure:
    """Base for the per-infrastructure FieldDeviceConfig built in configs.py."""

    INFRA = ""

    def __init__(self) -> None:
        self.infrastructure_name = self.INFRA
        self.range = INFRASTRUCTURES[self.INFRA]["range"] if self.INFRA else (0, 1)

    @classmethod
    def create_device(
        cls,
        device_type: str,
        device_name: str,
        protocol: str,
        reg_config: dict[str, Any] | list[dict[str, Any]],
        **kwargs: list[str | int],
    ) -> Device:
        """Build one device. AppError if the type is not in the table.

        kwargs are per-field overrides, e.g. analog-read=["voltage"].
        """

        devices = INFRASTRUCTURES[cls.INFRA]["devices"]
        name = device_type.lower().strip() if isinstance(device_type, str) else ""

        if name not in devices:
            raise error.AppError(
                f"device type '{device_type}' is not valid for {cls.INFRA}; "
                f"valid types: {', '.join(sorted(devices))}"
            )

        spec = devices[name]
        return Device(
            device_type,
            device_name,
            protocol,
            reg_config,
            fields={f: kwargs.get(f, spec.get(f, [])) for f in FIELD_TYPES},
            range_=spec.get("range", INFRASTRUCTURES[cls.INFRA]["range"]),
            infrastructure=cls.INFRA,
        )
