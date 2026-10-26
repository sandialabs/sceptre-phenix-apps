from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Hostname, Interface, MetadataBlock
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# ettercap's -M method: one of its MITM attacks, optionally with an argument
# (arp:remote, icmp:MAC/IP, dhcp:ip_pool/netmask/dns). It goes straight into the
# command line, so the argument is restricted to safe characters.
Method = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(arp|icmp|dhcp|port|ndp)(:[A-Za-z0-9_.:,/-]+)?$",
    ),
]

# ettercap TARGET definitions: space-separated /MAC/IPs/PORTs/ triples (ranges
# with '-', lists with ','). These are appended to the shell command, so the
# pattern allows only the characters a target can contain and nothing a shell
# would act on. No token may start with '-', or it would reach ettercap as an
# option (e.g. "-D /10.0.0.1//").
Targets = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[0-9A-Fa-f:.,/][0-9A-Fa-f:.,/-]*( [0-9A-Fa-f:.,/][0-9A-Fa-f:.,/-]*)*$",
    ),
]


class EttercapVM(MetadataBlock):
    hostname: Hostname
    interface: Interface
    targets: Targets
    method: Method = "arp"


class EttercapMetadata(BaseModel):
    """Metadata for the ettercap component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    vms: Annotated[list[EttercapVM], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_vms(self) -> Self:
        seen = [(vm.hostname, vm.interface) for vm in self.vms]
        if dupes := sorted({f"{h} {i}" for h, i in seen if seen.count((h, i)) > 1}):
            raise ValueError(
                f"vms: ettercap started more than once on: {', '.join(dupes)}; "
                "one MITM per host interface"
            )
        return self


class Ettercap(ComponentBase):
    metadata_model = EttercapMetadata
    config: EttercapMetadata

    def __init__(self):
        ComponentBase.__init__(self, "ettercap")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        for vm in self.config.vms:
            logger.info(f"ensuring interface {vm.interface} is up in VM {vm.hostname}")

            with utils.mm_cc_filter(self.mm, f"name={vm.hostname}"):
                self.mm.cc_exec(f"ip link set {vm.interface} up")

                logger.info(
                    f"starting ettercap using {vm.method} against {vm.targets} "
                    f"in VM {vm.hostname}"
                )

                self.mm.cc_background(
                    f"ettercap -Tq -i {vm.interface} -M {vm.method} {vm.targets}"
                )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        for vm in self.config.vms:
            logger.info(f"stopping ettercap in VM {vm.hostname}")

            with utils.mm_cc_filter(self.mm, f"name={vm.hostname}"):
                self.mm.cc_exec("pkill ettercap")

        logger.info(f"Stopped user component: {self.name}")


def main():
    Ettercap()


if __name__ == "__main__":
    main()
