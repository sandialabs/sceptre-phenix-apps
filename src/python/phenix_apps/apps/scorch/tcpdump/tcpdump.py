import subprocess
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    Args,
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# TODO: merge tcpdump's functionality into the 'pcap' component

# options and filter only reach tcpdump inside the guest (through `bash -c '...'`,
# hence no single quotes); empty means none
GuestText = Annotated[Args, StringConstraints(strip_whitespace=True)]


class VM(MetadataBlock):
    hostname: Hostname
    iface: Interface
    options: GuestText = ""
    filter: GuestText = ""


class TCPDumpMetadata(BaseModel):
    """Metadata for the tcpdump component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    vms: Annotated[list[VM], Field(min_length=1)]
    convertToJSON: bool = False
    convertTimeout: PositiveSeconds = 600.0

    @model_validator(mode="after")
    def _check_vms(self) -> Self:
        seen = [(vm.hostname, vm.iface) for vm in self.vms]
        if dupes := sorted({f"{h} {i}" for h, i in seen if seen.count((h, i)) > 1}):
            raise ValueError(
                f"vms: captured more than once: {', '.join(dupes)}; each capture "
                "writes the same file"
            )
        return self


class TCPDump(ComponentBase):
    metadata_model = TCPDumpMetadata
    config: TCPDumpMetadata

    def __init__(self):
        ComponentBase.__init__(self, "tcpdump")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        self._check_stage_lists()

        for vm in self.config.vms:
            pcap = f"/dump-{vm.iface}.pcap"
            pidfile = f"/dump-{vm.iface}.pid"

            # mm_exec_wait raises if the VM does not exist or its miniccc client
            # never registers, which covers "VM is not running".
            res = utils.mm_exec_wait(self.mm, vm.hostname, "which tcpdump")
            if not res["stdout"]:
                raise RuntimeError(f"tcpdump is not installed in VM {vm.hostname}")

            res = utils.mm_exec_wait(self.mm, vm.hostname, f"ip link show {vm.iface}")
            if res["exitcode"] != 0:
                raise RuntimeError(
                    f"interface {vm.iface} does not exist in VM {vm.hostname}"
                )

            # a pid file left by a failed stop or cleanup; stop its tcpdump so
            # the new capture does not fight it over the file
            res = utils.mm_exec_wait(
                self.mm,
                vm.hostname,
                f"bash -c 'if [ -s {pidfile} ]; then pid=$(cat {pidfile}); "
                f"if [ $(cat /proc/$pid/comm) = tcpdump ]; then kill $pid; echo killed; fi; "
                f"rm -f {pidfile}; fi'",
            )
            if res["stdout"]:
                logger.warning(
                    f"stopped a tcpdump left running in VM {vm.hostname} by an "
                    f"earlier run ({pidfile})"
                )

            logger.info(f"starting tcpdump on interface {vm.iface} in VM {vm.hostname}")

            if vm.filter:
                logger.info(f"using filter {vm.filter} for tcpdump in VM {vm.hostname}")

            # exec keeps the shell's PID for tcpdump, so the pid file is
            # tcpdump's; "$@" hands the options and filter over as-is, without
            # the shell parsing the filter's parentheses and such
            utils.mm_cc_filter_vm(self.mm, vm.hostname)
            self.mm.cc_exec(f"ip link set {vm.iface} up")
            self.mm.cc_background(
                f"bash -c 'echo $$ > {pidfile}; exec tcpdump \"$@\"' tcpdump "
                f"{vm.options} -i {vm.iface} -U -w {pcap} {vm.filter}"
            )

        self.mm.clear_cc_filter()

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        if self.config.convertToJSON:
            logger.info("PCAP --> JSON conversion enabled... please be patient")
        else:
            logger.info("PCAP --> JSON conversion disabled")

        for vm in self.config.vms:
            pcap_out = f"{self.base_dir}/{vm.hostname}-{vm.iface}.pcap"
            json_out = f"{pcap_out}.jsonl"
            pidfile = f"/dump-{vm.iface}.pid"

            res = utils.mm_exec_wait(
                self.mm, vm.hostname, f"bash -c 'kill $(cat {pidfile})'"
            )
            if res["exitcode"] != 0:
                # the capture may be incomplete, but it is still worth collecting
                logger.error(
                    f"could not stop tcpdump in VM {vm.hostname} using {pidfile}: "
                    f"{res['stderr']}"
                )

            logger.info(f"copying PCAP file from node {vm.hostname}...")

            utils.mm_recv(self.mm, vm.hostname, f"/dump-{vm.iface}.pcap", pcap_out)
            # target the VM explicitly (by UUID, like the helpers above); this
            # used to rely on whichever filter they happened to leave behind
            utils.mm_cc_filter_vm(self.mm, vm.hostname)
            self.mm.cc_exec(f"rm -f /dump-{vm.iface}.pcap {pidfile}")
            self.mm.clear_cc_filter()

            logger.info(f"done copying PCAP file from node {vm.hostname}")

            if self.config.convertToJSON:
                logger.info(
                    f"starting PCAP --> JSON conversion for node {vm.hostname}..."
                )

                if self._convert(pcap_out, json_out):
                    logger.info(
                        f"PCAP --> JSON conversion for node {vm.hostname} complete"
                    )

        logger.info(f"Stopped user component: {self.name}")

    def _convert(self, pcap: str, jsonl: str) -> bool:
        """Convert a capture with tshark. Conversion is post-processing, so a
        failure or timeout is logged as an error and the stage carries on."""

        try:
            with open(jsonl, "w") as out:
                proc = subprocess.run(
                    ["tshark", "-r", pcap, "-T", "ek"],
                    stdout=out,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.config.convertTimeout,
                )
        except subprocess.TimeoutExpired:
            logger.error(
                f"PCAP --> JSON conversion of {pcap} timed out after "
                f"{self.config.convertTimeout}s; {jsonl} is incomplete. "
                "Raise convertTimeout for large captures."
            )
            return False
        except OSError as ex:
            logger.error(f"PCAP --> JSON conversion of {pcap} could not run: {ex}")
            return False

        if proc.returncode != 0:
            logger.error(
                f"PCAP --> JSON conversion of {pcap} failed (tshark exit "
                f"{proc.returncode}): {proc.stderr.strip()}"
            )
            return False

        return True

    def _check_stage_lists(self) -> None:
        """Warn when this component is started but never stopped, or stopped
        after the collector, which would then miss the capture files."""

        scorch = self.extract_app("scorch").get("metadata") or {}
        runs = scorch.get("runs") or []
        if self.run >= len(runs):
            return

        run = runs[self.run]
        collectors = {
            c.name
            for c in scorch.get("components") or []
            if (c.get("type") or c.name) == "collector"
        }

        # stage lists are at the top of a run and, if it has one, under `loop`
        for scope in (run, run.get("loop") or {}):
            if self.name not in (scope.get("start") or []):
                continue

            stop = scope.get("stop") or []
            if self.name not in stop:
                logger.warning(
                    f"{self.name} is in a start list but not in the matching stop "
                    "list; its captures will not be collected"
                )
            elif any(c in stop[: stop.index(self.name)] for c in collectors):
                logger.warning(
                    f"{self.name} is listed after the collector in stop; list it "
                    "before, or the collector will miss its capture files"
                )


def main():
    TCPDump()


if __name__ == "__main__":
    main()
