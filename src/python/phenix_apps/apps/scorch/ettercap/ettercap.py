from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger


class Ettercap(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "ettercap")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.get("hostname", None)
            iface = vm.get("iface", None)
            method = vm.get("method", "arp")
            targets = vm.get("targets", None)

            if not hostname:
                continue

            if not iface:
                self.printf(f"missing interface name for VM {hostname}")
                continue

            if not targets:
                self.printf(f"missing targets for VM {hostname}")
                continue

            self.print(f"ensuring interface {iface} is up in VM {hostname}")

            cmd = f"ip link set {iface} up"

            mm.cc_filter(f"name={hostname}")
            mm.cc_exec(cmd)

            self.print(
                f"starting ettercap using {method} against {targets} in VM {hostname}"
            )

            cmd = f"ettercap -Tq -i {iface} -M {method} {targets}"

            mm.cc_background(cmd)

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.get("hostname", None)

            if not hostname:
                continue

            self.print(f"stopping ettercap in VM {hostname}")

            mm.cc_filter(f"name={hostname}")
            mm.cc_exec("pkill ettercap")

        logger.info(f"Stopped user component: {self.name}")


def main():
    Ettercap()


if __name__ == "__main__":
    main()
