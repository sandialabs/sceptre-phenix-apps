import json
import time
from typing import Annotated, Any

from pydantic import Field, PositiveInt

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import MetadataBlock, Seconds
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# VM names (or shorthand like load[1-5]) go into minimega `vm tag` commands and
# into host file names: one word, no quotes or slashes.
VMName = Annotated[str, Field(pattern=r"""^[^\s'"/]+$""")]


class VMStatsMetadata(MetadataBlock):
    """Metadata for the vmstats component; see README.md for each field."""

    # vmstat's delay argument: whole seconds
    pollPeriod: PositiveInt = 1
    # None: every Linux VM
    vms: list[VMName] | None = Field(None, min_length=1)
    # time for vmstat to be killed and its output flushed before collecting
    stopWait: Seconds = 5.0
    # read by phenix, not by this component
    filebeat_inputs: list[dict[str, Any]] | None = Field(None, alias="filebeat.inputs")


def parse_vmstat(text: str, vm: str) -> tuple[list[dict], int]:
    """Parse `vmstat -n -t` output into one record per sample.

    Returns the records and the number of lines skipped. Lines are skipped when
    they are not samples: the column headers, which reappear if miniccc reruns
    vmstat after the VM reconnects, and a last line cut short by the kill.
    """

    header: list[str] | None = None
    stats = []
    skipped = 0

    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("procs"):
            continue
        if fields[0] == "r":
            header = fields  # its last column names the timezone, e.g. UTC
            continue
        # a sample has the numeric columns plus a date and a time, which fill
        # the header's one timezone column
        if header is None or not fields[0].isdigit() or len(fields) != len(header) + 1:
            skipped += 1
            continue

        items: list[int | str] = []
        for item in fields:
            try:
                items.append(int(item))
            except ValueError:
                items.append(item)
        items[-2:] = [f"{items[-2]} {items[-1]}"]

        stat: dict[str, int | str] = dict(zip(header, items, strict=True))
        stat["vm_name"] = vm
        stats.append(stat)

    return stats, skipped


class VMStats(ComponentBase):
    """
    Collects resource utilization statistics from VMs in the experiment, using the `vmstats` command.
    """

    metadata_model = VMStatsMetadata
    config: VMStatsMetadata

    def __init__(self):
        ComponentBase.__init__(self, "vmstats")
        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        freq = self.config.pollPeriod
        vms = self.__vm_list()

        for vm in vms:
            self.mm.vm_tag(vm, "vmstat", "1")

        self.mm.clear_cc_prefix()
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_background(f"bash -c 'vmstat -n -t {freq} >> /vmstat.out'")
        self.mm.clear_cc_filter()

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.__vm_list()

        logger.info("killing vmstat processes")
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_exec_once("pkill vmstat")
        self.mm.clear_cc_filter()

        time.sleep(self.config.stopWait)

        # Collect every VM that has its file before failing for the ones that
        # do not, so one missing VM does not lose everyone else's stats.
        collected, failed = [], {}
        for i, vm in enumerate(vms):
            logger.info(f"transferring /vmstat.out from {vm} ({i + 1} of {len(vms)})")
            try:
                utils.mm_recv(
                    self.mm, vm, "/vmstat.out", str(self.base_dir / f"{vm}.out")
                )
                collected.append(vm)
            except ValueError as ex:
                logger.error(f"Failed to get vmstat.out from {vm}: {ex}")
                failed[vm] = str(ex)

        logger.info("deleting vmstat.out from VMs")
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_exec_once("rm /vmstat.out")
        self.mm.clear_cc_filter()

        stats = []

        logger.info("reading vmstat.out files")
        for vm in collected:
            vm_stats, skipped = parse_vmstat(
                (self.base_dir / f"{vm}.out").read_text(), vm
            )
            if skipped:
                logger.warning(f"skipped {skipped} unreadable line(s) from {vm}")
            stats.extend(vm_stats)

        stats_path = self.base_dir / "vm_stats.jsonl"
        logger.info(f"writing consolidated vmstats to {stats_path}")
        with stats_path.open("a+") as f:
            for datum in stats:
                json_record = json.dumps(datum)
                f.write(json_record + "\n")

        if failed:
            raise RuntimeError(
                f"no vmstat.out from {len(failed)} VM(s) (the others were "
                f"collected): {', '.join(sorted(failed))}"
            )

        logger.info(f"Stopped user component: {self.name}")

    def __vm_list(self) -> list:
        vms = self.config.vms
        compatible_os = ["linux", "centos", "rhel"]

        if vms:  # if specific vms are configured in metadata
            expanded = []

            for vm in vms:
                expanded.append(utils.expand_shorthand(vm))

            vms = [e for sub in expanded for e in sub]
        else:  # default to all linux VMs
            vms = []
            for vm in self.extract_node_names():
                node = self.extract_node(vm)

                if node.get("hardware", {}).get("os_type", "") in compatible_os:
                    vms.append(vm)
                else:
                    logger.info(
                        f"Skipping VM {vm} with incompatible os_type '{node.get('hardware', {}).get('os_type', '')}' (must be one of {compatible_os})"
                    )

        return vms


def main():
    VMStats()


if __name__ == "__main__":
    main()
