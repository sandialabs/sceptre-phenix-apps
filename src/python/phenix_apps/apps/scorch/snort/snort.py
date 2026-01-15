import csv
import json
import os
import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Snort(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "snort")

        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        scripts = self.metadata.get("scripts", {})
        configs = self.metadata.get("configs", [])

        mm = self.mm_init()

        config_snort = scripts.get("configSnort", None)

        if config_snort:
            script = config_snort["script"]
            executor = config_snort["executor"]

            self.print(f"copying {os.path.basename(script)} to {hostname}")

            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/snort-test/scripts/configure-snort.sh, then it
            # will be copied to /configure-snort.sh in the VM.
            utils.mm_send(mm, hostname, script, os.path.basename(script))

            self.print(f"running {os.path.basename(script)} on {hostname}")

            mm.cc_filter(f"name={hostname}")
            mm.cc_exec(f"{executor} /{os.path.basename(script)}")

        for config in configs:
            src = config["src"]
            dst = config["dst"]

            self.print(f"copying {os.path.basename(src)} to {hostname}")

            utils.mm_send(mm, hostname, src, dst)

        iface = self.metadata.get("sniffInterface", "eth0")

        self.print(f"ensuring {iface} is up in {hostname}")

        mm.cc_filter(f"name={hostname}")
        mm.cc_exec(f"ip link set {iface} up")

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        iface = self.metadata.get("sniffInterface", "eth0")

        mm = self.mm_init()

        self.print(f"clearing existing Snort logs in {hostname}")

        mm.cc_filter(f"name={hostname}")
        mm.cc_exec("rm -rf /var/log/snort")
        mm.cc_exec("mkdir -p /var/log/snort")

        self.print(f"starting Snort in {hostname}")

        mm.cc_filter(f"name={hostname}")
        mm.cc_background(f"snort -i {iface} -c /etc/snort/snort.conf")

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        wait = self.metadata.get("waitDuration", 30)

        mm = self.mm_init()

        self.print(f"waiting {wait} seconds before stopping Snort in {hostname}")

        time.sleep(wait)

        self.print(f"stopping Snort in {hostname} (be patient... it may take a while)")

        mm.cc_filter(f"name={hostname}")
        mm.cc_exec("pkill -INT snort")

        logfiles = ["alert", "snort.log", "snort.stats"]

        for log in logfiles:
            self.print(f"copying /var/log/snort/{log} from {hostname}")
            utils.mm_recv(
                mm, hostname, f"/var/log/snort/{log}", f"{self.base_dir}/{log}"
            )

            if log == "snort.stats" and os.path.exists(f"{self.base_dir}/{log}"):
                self.print("converting snort.stats to JSON")

                lines = []

                with open(f"{self.base_dir}/{log}") as f:
                    lines = f.readlines()

                # get rid of comment in file
                lines.pop(0)

                # remove comment field from header line
                header = lines.pop(0)
                header = header.replace("#", "")

                lines.insert(0, header)

                data = csv.DictReader(lines)

                with open(f"{self.base_dir}/snort-stats.jsonl", "w") as f:
                    for row in data:
                        out = {
                            "timestamp": int(row["time"]),
                            "total_alerts_per_second": int(
                                row["total_alerts_per_second"]
                            ),
                        }

                        json.dump(row, f)
                        f.write("\n")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        logfiles = ["snort.log", "snort.err", "snort.stats"]

        mm = self.mm_init()

        for log in logfiles:
            self.print(f"deleting /var/log/snort/{log} from {hostname}")

            mm.cc_filter(f"name={hostname}")
            mm.cc_exec(f"rm /var/log/snort/{log}")

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Snort()


if __name__ == "__main__":
    main()
