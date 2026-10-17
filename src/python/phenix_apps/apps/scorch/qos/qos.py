import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Final, Self

from box import Box
from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Hostname, Interface, MetadataBlock
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


# Like minimega (cliParseQos retries with "ms" appended), a bare number such as
# 100 means ms.
def _bare_ms(v: object) -> object:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if isinstance(v, str):
        v = v.strip().lower()
        if re.fullmatch(r"\d+\.?\d*|\.\d+", v):
            v += "ms"
    return v


# A Go duration, as minimega parses it: 100ms, 1s, 1m30s, .5s, 1.s. Each part
# needs a digit on one side of the optional point, and a unit.
# ponytail: no leading sign (delay cannot be negative).
Duration = Annotated[
    str,
    BeforeValidator(_bare_ms),
    Field(pattern=r"^((\d+\.?\d*|\.\d+)(ns|us|µs|μs|ms|s|m|h))+$"),
]
_RATE: Final = re.compile(r"^(\d+(?:\.\d+)?)\s*(kbit|mbit|gbit)$")
_UNITS: Final = ("kbit", "mbit", "gbit")


def _rate(value: str) -> str:
    match = _RATE.fullmatch(value.strip().lower())
    if not match:
        raise ValueError("must be a number and kbit, mbit or gbit, like '500 kbit'")
    # minimega parses the rate with strconv.ParseUint, so it must be a whole number:
    # step a fraction down to a smaller unit (1.5 mbit -> 1500 kbit).
    number, unit = Decimal(match[1]), _UNITS.index(match[2])
    while number != number.to_integral_value() and unit > 0:
        number, unit = number * 1000, unit - 1
    if number != number.to_integral_value():
        raise ValueError(
            "must be a whole number of kbit, like '1500 kbit' (not 1.0005 mbit)"
        )
    return f"{int(number)} {_UNITS[unit]}"


class VMQoS(MetadataBlock):
    hostname: Hostname
    # an index into the node's interfaces, or an interface name
    interface: NonNegativeInt | Interface = 0
    loss: Annotated[float, Field(ge=0.0, lt=100.0)] | None = None
    variable_loss: NonNegativeFloat | None = None
    delay: Duration | None = None
    rate: Annotated[str, AfterValidator(_rate)] | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        losses = self.loss is not None or self.variable_loss is not None
        if not (losses or self.delay or self.rate):
            raise ValueError("needs one of loss, variable_loss, delay or rate")
        # tc, which minimega uses, cannot combine a rate with loss or delay
        if self.rate and (losses or self.delay):
            raise ValueError("rate cannot be combined with loss or delay")
        if self.variable_loss is None and self.loss is not None and self.loss > 99.9:
            raise ValueError("loss must be 0.0 to 99.9 (minimega cannot drop 100%)")
        return self

    def loss_for(self, count: int) -> float | None:
        """Loss to apply in SCORCH iteration `count`: variable_loss x count, if set."""
        if self.variable_loss is not None:
            return self.variable_loss * count
        return self.loss


class QoSMetadata(MetadataBlock):
    """Metadata for the qos component; see README.md for each field.

    A MetadataBlock, so unknown keys are warned about; the collector reads
    qos_values_applied.json, not this block.
    """

    vms: list[VMQoS]


class QoS(ComponentBase):
    """
    Implements minimega's "qos" API for applying quality of service (QoS) limits.
    """

    metadata_model = QoSMetadata
    config: QoSMetadata

    def __init__(self):
        ComponentBase.__init__(self, "qos")
        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        values_applied: dict[str, dict] = defaultdict(dict)
        vms = self.config.vms
        logger.info(f"applying qos to {len(vms)} VMs")

        for i, vm in enumerate(vms):
            hostname, interface = self.get_host_and_iface(Box(vm.model_dump()))
            where = f"interface {interface} on node {hostname} ({i + 1} of {len(vms)})"

            values_applied[hostname]["interface"] = interface

            loss = vm.loss_for(self.count)
            if loss is not None:
                if vm.variable_loss is not None:
                    logger.info(
                        f"variable_loss is set, {vm.variable_loss} * {self.count} => {loss} loss for run iteration {self.count}"
                    )
                if loss > 99.9:
                    raise ValueError(
                        f"loss of {loss} for {hostname} is not between 0.0 - 99.9 (note: 100% loss is not possible with minimega)"
                    )
                logger.info(f"adding loss of {loss} to {where}")
                self.mm.qos_add_loss(hostname, interface, loss)
                values_applied[hostname]["loss"] = loss

            if vm.delay is not None:
                logger.info(f"adding delay of {vm.delay} to {where}")
                self.mm.qos_add_delay(hostname, interface, vm.delay)
                values_applied[hostname]["delay"] = vm.delay

            if vm.rate is not None:
                bw, unit = vm.rate.split(" ")
                logger.info(f"adding rate limit of {bw} {unit} to {where}")
                self.mm.qos_add_rate(hostname, interface, bw, unit)
                values_applied[hostname]["rate"] = vm.rate

        qos_path = Path(self.base_dir, "qos_values_applied.json")
        logger.info(f"saving qos values applied to {qos_path}")
        utils.write_json(qos_path, values_applied)

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.config.vms
        logger.info(f"clearing qos from {len(vms)} VMs")
        for i, vm in enumerate(vms):
            hostname, interface = self.get_host_and_iface(Box(vm.model_dump()))
            logger.info(
                f"clearing qos for interface {interface} on node {hostname} ({i + 1} of {len(vms)})"
            )
            self.mm.clear_qos(hostname, interface)

        logger.info(f"Stopped user component: {self.name}")


def main():
    QoS()


if __name__ == "__main__":
    main()
