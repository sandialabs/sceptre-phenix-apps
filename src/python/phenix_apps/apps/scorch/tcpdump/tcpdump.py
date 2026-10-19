import re
import subprocess
from pathlib import Path
from typing import Final

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import error, utils
from phenix_apps.common.logger import logger

# TODO: merge tcpdump's functionality into the 'pcap' component

IFACE_REGEX: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")


def _validate_iface(iface: str) -> str:
    if not IFACE_REGEX.fullmatch(iface):
        raise error.AppError(f"invalid interface name '{iface}'")
    return iface


class TCPDump(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "tcpdump")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.get("hostname", None)
            iface = vm.get("iface", None)
            options = vm.get("options", "")
            bpf_filter = vm.get("filter", "")

            if not hostname:
                raise ValueError("no hostname provided for VM config")

            if not iface:
                raise ValueError("no interface name provided for VM config")

            iface = _validate_iface(iface)

            res = utils.mm_exec_wait(mm, hostname, "which tcpdump")
            if not res["stdout"]:
                raise RuntimeError(f"tcpdump is not installed in VM {hostname}")

            logger.info(f"starting tcpdump on interface {iface} in VM {hostname}")

            if bpf_filter:
                logger.info(f"using filter {bpf_filter} for tcpdump in VM {hostname}")

            mm.cc_filter(f"name={hostname}")
            mm.cc_exec(f"ip link set {iface} up")
            mm.cc_background(
                f"tcpdump {options} -i {iface} -U -w /dump-{iface}.pcap {bpf_filter}"
            )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        convert = self.metadata.get("convertToJSON", False)

        if convert:
            logger.info("PCAP --> JSON conversion enabled... please be patient")
        else:
            logger.info("PCAP --> JSON conversion disabled")

        for vm in vms:
            hostname = vm.get("hostname", None)
            iface = vm.get("iface", None)

            if not hostname:
                raise ValueError("no hostname provided for VM config")

            if not iface:
                raise ValueError("no interface name provided for VM config")

            iface = _validate_iface(iface)

            pcap_out = str(Path(self.base_dir) / f"{hostname}-{iface}.pcap")
            json_out = Path(self.base_dir) / f"{hostname}-{iface}.pcap.jsonl"

            utils.mm_exec_wait(mm, hostname, "pkill tcpdump")

            logger.info(f"copying PCAP file from node {hostname}...")

            utils.mm_recv(mm, hostname, f"/dump-{iface}.pcap", pcap_out)
            mm.cc_exec(f"rm /dump-{iface}.pcap")

            logger.info(f"done copying PCAP file from node {hostname}")

            if convert:
                logger.info(f"starting PCAP --> JSON conversion for node {hostname}...")

                with json_out.open("w") as jf:
                    subprocess.run(
                        ["tshark", "-r", pcap_out, "-T", "ek"],
                        stdout=jf,
                        stderr=subprocess.DEVNULL,
                    )

                logger.info(f"PCAP --> JSON conversion for node {hostname} complete")

        logger.info(f"Stopped user component: {self.name}")


def main():
    TCPDump()


if __name__ == "__main__":
    main()
