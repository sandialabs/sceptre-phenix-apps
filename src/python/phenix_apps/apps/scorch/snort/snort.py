import csv
import json
import time
from pathlib import PurePath

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    Interface,
    MetadataBlock,
    Name,
    Seconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class ConfigFile(MetadataBlock):
    src: FilePath  # a path on the phenix server
    dst: FilePath  # where to drop it in the VM
    name: Name | None = None  # optional label; not used by the component


class ConfigScript(MetadataBlock):
    script: FilePath  # a path on the phenix server
    executor: FilePath  # the interpreter to run it with, e.g. bash


class Scripts(MetadataBlock):
    configSnort: ConfigScript | None = None


class SnortMetadata(BaseModel):
    """Metadata for the snort component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    hostname: Hostname = "detector"
    interface: Interface = Field(
        "eth0", validation_alias=AliasChoices("interface", "sniffInterface")
    )
    waitDuration: Seconds = 30.0
    configs: list[ConfigFile] = Field(default_factory=list)
    scripts: Scripts = Field(default_factory=Scripts)


class Snort(ComponentBase):
    metadata_model = SnortMetadata
    config: SnortMetadata

    def __init__(self):
        ComponentBase.__init__(self, "snort")

        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        hostname = self.config.hostname
        iface = self.config.interface

        config_snort = self.config.scripts.configSnort

        if config_snort:
            script = config_snort.script
            executor = config_snort.executor
            script_name = PurePath(script).name

            logger.info(f"copying {script_name} to {hostname}")

            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/snort-test/scripts/configure-snort.sh, then it
            # will be copied to /configure-snort.sh in the VM.
            utils.mm_send(self.mm, hostname, script, script_name)

            logger.info(f"running {script_name} on {hostname}")

            with utils.mm_cc_filter(self.mm, f"name={hostname}"):
                self.mm.cc_exec(f"{executor} /{script_name}")

        for config in self.config.configs:
            logger.info(f"copying {PurePath(config.src).name} to {hostname}")

            utils.mm_send(self.mm, hostname, config.src, config.dst)

        logger.info(f"ensuring {iface} is up in {hostname}")

        with utils.mm_cc_filter(self.mm, f"name={hostname}"):
            self.mm.cc_exec(f"ip link set {iface} up")

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        hostname = self.config.hostname
        iface = self.config.interface

        logger.info(f"clearing existing Snort logs in {hostname}")

        with utils.mm_cc_filter(self.mm, f"name={hostname}"):
            self.mm.cc_exec("rm -rf /var/log/snort")
            self.mm.cc_exec("mkdir -p /var/log/snort")

        logger.info(f"starting Snort in {hostname}")

        with utils.mm_cc_filter(self.mm, f"name={hostname}"):
            self.mm.cc_background(f"snort -i {iface} -c /etc/snort/snort.conf")

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        hostname = self.config.hostname
        wait = self.config.waitDuration

        logger.info(f"waiting {wait} seconds before stopping Snort in {hostname}")

        time.sleep(wait)

        logger.info(f"stopping Snort in {hostname} (be patient... it may take a while)")

        with utils.mm_cc_filter(self.mm, f"name={hostname}"):
            self.mm.cc_exec("pkill -INT snort")

        logfiles = ["alert", "snort.log", "snort.stats"]

        for log in logfiles:
            log_path = self.base_dir / log

            logger.info(f"copying /var/log/snort/{log} from {hostname}")
            utils.mm_recv(self.mm, hostname, f"/var/log/snort/{log}", str(log_path))

            if log == "snort.stats" and log_path.is_file():
                with log_path.open() as f:
                    lines = f.readlines()

                # a comment line, then the header; nothing to convert without both
                if len(lines) < 2:
                    logger.info("snort.stats has no header, skipping JSON conversion")
                    continue

                logger.info("converting snort.stats to JSON")

                # get rid of comment in file
                lines.pop(0)

                # remove comment field from header line
                header = lines.pop(0)
                header = header.replace("#", "")

                lines.insert(0, header)

                data = csv.DictReader(lines)

                with (self.base_dir / "snort-stats.jsonl").open("w") as f:
                    for row in data:
                        json.dump(row, f)
                        f.write("\n")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        hostname = self.config.hostname
        logfiles = ["snort.log", "snort.err", "snort.stats"]

        with utils.mm_cc_filter(self.mm, f"name={hostname}"):
            for log in logfiles:
                logger.info(f"deleting /var/log/snort/{log} from {hostname}")

                self.mm.cc_exec(f"rm /var/log/snort/{log}")

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Snort()


if __name__ == "__main__":
    main()
