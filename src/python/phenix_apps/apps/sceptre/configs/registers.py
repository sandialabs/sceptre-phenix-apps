"""Devices and their registers: what a field device exposes over the wire.

`Device` holds one device's field lists; `Register` turns each field into an
address in the protocol's address space. Kept apart from infrastructures.py so
that file is the table and this one is the logic.
"""

from typing import Any, ClassVar

import phenix_apps.apps.sceptre.protocols.sunspec as sunspec


class Device:
    def __init__(
        self,
        device_type: str,
        device_name: str,
        protocol: str,
        reg_config: dict[str, Any] | list[dict[str, Any]],
        fields: dict[str, list[str | int]],
        range_: tuple[float, float],
        infrastructure: str,
    ) -> None:
        self.device_type = device_type
        self.device_name = device_name
        self.protocol = protocol
        self.reg_config = reg_config
        self.fields = fields
        self.range = range_
        self.infrastructure = infrastructure
        self.registers = []
        self.__generate_register_list()

    def __generate_register_list(self) -> None:
        for field_type, fields in self.fields.items():
            if self.protocol == "sunspec":
                # Only an inverter has a SunSpec map, and its models live in the
                # analog-read-write list.
                if self.device_type == "inverter" and field_type == "analog-read-write":
                    sunspec.SunSpecDevice(
                        self.infrastructure, self.device_name, self.registers
                    ).generate_registers(fields)
                continue

            self.registers += [
                Register(
                    self.device_name,
                    field,
                    field_type,
                    self.device_type,
                    self.protocol,
                    self.range,
                    self.reg_config,
                )
                for field in fields
            ]


class Register:
    # Protocol -> what each field type is called in that protocol's address space.
    ANALOG: ClassVar[dict[str, str]] = {
        "analog-read": "analog-input",
        "analog-read-write": "analog-output",
        "binary-read": "binary-input",
        "binary-read-write": "binary-output",
    }
    MODBUS: ClassVar[dict[str, str]] = {
        "analog-read": "input-register",
        "analog-read-write": "holding-register",
        "binary-read": "discrete-input",
        "binary-read-write": "coil",
    }
    TYPE: ClassVar[dict[str, dict[str, str]]] = {
        "dnp3": ANALOG,
        "dnp3-serial": ANALOG,
        "modbus": MODBUS,
        "modbus-serial": MODBUS,
        "bacnet": ANALOG,
        "iec60870-5-104": ANALOG,
    }

    # Next free address per protocol or register type. Class-level on purpose:
    # numbering runs across every device in one field device config, and
    # configs.py resets it between them.
    START: ClassVar[dict[str, int]] = {
        "dnp3": 0,
        "dnp3-serial": 0,
        "bacnet": 0,
        "iec60870-5-104": 1,
        "input-register": 30000,
        "holding-register": 40000,
        "discrete-input": 10000,
        "coil": 0,
        "float-point": 1000,
        "single-point": 3000,
    }
    addresses: ClassVar[dict[str, int]] = dict(START)

    def __init__(
        self,
        devname: str,
        field: str,
        fieldtype: str,
        devtype: str,
        protocol: str,
        range_: tuple[float, float],
        reg_config: dict[str, Any] | list[dict[str, Any]],
    ) -> None:
        self.devname = devname
        self.field = field
        self.fieldtype = fieldtype
        self.regtype = type(self).TYPE[protocol][fieldtype]
        self.protocol = protocol
        self.devtype = devtype
        self.range = range_

        # Protocol-wide register numbers used for DNP3 registers
        if not bool(reg_config):
            if (
                "dnp3" in self.protocol
                or "bacnet" in self.protocol
                or "iec60870-5-104" in self.protocol
            ):
                self.addr = type(self).addresses[self.protocol]
                type(self).addresses[self.protocol] += 1
            else:
                self.addr = type(self).addresses[self.regtype]
                type(self).addresses[self.regtype] += 1
        else:
            for config in reg_config:
                if (
                    self.fieldtype in config.keys()
                    and self.devname == config["name"]
                    and self.devtype == config["type"]
                ):
                    for item in config[self.fieldtype]:
                        if (
                            self.field == item["field"]
                            and self.regtype == item["register_type"]
                        ):
                            register_number = item["register_number"]
                            if (
                                "dnp3" in self.protocol
                                or "bacnet" in self.protocol
                                or "iec60870-5-104" in self.protocol
                            ):
                                self.addr = type(self).addresses[self.protocol]
                                type(self).addresses[self.protocol] = register_number
                            else:
                                self.addr = type(self).addresses[self.regtype]
                                type(self).addresses[self.regtype] = register_number

            # DEFAULT: if something isn't right
            if (
                "dnp3" in self.protocol
                or "bacnet" in self.protocol
                or "iec60870-5-104" in self.protocol
            ):
                self.addr = type(self).addresses[self.protocol]
                type(self).addresses[self.protocol] += 1
            else:
                self.addr = type(self).addresses[self.regtype]
                type(self).addresses[self.regtype] += 1

    @staticmethod
    def reset_addresses() -> None:
        Register.addresses = dict(Register.START)
