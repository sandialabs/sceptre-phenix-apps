import shlex
import subprocess
from pathlib import Path
from typing import Annotated, Any, Self

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
    FilterExpr,
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# TODO: merge tcpdump's functionality into the 'pcap' component

# options and filter are shell-quoted into the launcher script sent to the guest
# (hence no single quotes); empty means none
GuestOptions = Annotated[Args, StringConstraints(strip_whitespace=True)]
GuestFilter = Annotated[FilterExpr, StringConstraints(strip_whitespace=True)]


class VM(MetadataBlock):
    hostname: Hostname
    iface: Interface
    options: GuestOptions = ""
    filter: GuestFilter = ""


class TCPDumpMetadata(BaseModel):
    """Metadata for the tcpdump component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    vms: Annotated[list[VM], Field(min_length=1)]
    convert_to_json: bool = False
    convertTimeout: PositiveSeconds = 600.0

    @model_validator(mode="before")
    @classmethod
    def _convert_to_json_alias(cls, data: Any) -> Any:
        """`convertToJSON` is the deprecated name of `convert_to_json`."""

        if isinstance(data, dict) and "convertToJSON" in data:
            data = dict(data)
            old = data.pop("convertToJSON")
            logger.warning(
                "tcpdump: 'convertToJSON' is deprecated; rename it to 'convert_to_json'"
            )
            data.setdefault("convert_to_json", old)
        return data

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
            errfile = f"/dump-{vm.iface}.err"

            # mm_exec_wait raises if the VM does not exist or its miniccc client
            # never registers, which covers "VM is not running".
            res = utils.mm_exec_wait(self.mm, vm.hostname, "which tcpdump")
            if not res["stdout"]:
                raise RuntimeError(f"tcpdump is not installed in VM {vm.hostname}")

            # "any" is tcpdump's every-interface pseudo-device, not a link
            if vm.iface != "any":
                res = utils.mm_exec_wait(
                    self.mm, vm.hostname, f"ip link show {vm.iface}"
                )
                if res["exitcode"] != 0:
                    raise RuntimeError(
                        f"interface {vm.iface} does not exist in VM {vm.hostname}"
                    )

            # a pid file left by a failed stop or cleanup; stop its tcpdump so
            # the new capture does not fight it over the file. minimega expands
            # a bare $name in an inline cc command (to nothing), so only
            # $(...) is used here; anything else goes through a script file.
            res = utils.mm_exec_wait(
                self.mm,
                vm.hostname,
                f"bash -c 'if [ -s {pidfile} ] && "
                f"[ $(cat /proc/$(cat {pidfile})/comm) = tcpdump ]; "
                f"then kill $(cat {pidfile}); echo killed; fi; rm -f {pidfile}'",
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
            # tcpdump's; its stderr goes to a file in the VM, or a startup
            # failure would be invisible
            args = [*map(shlex.quote, shlex.split(vm.options))]
            args += ["-i", vm.iface, "-U", "-w", pcap]
            if vm.filter:
                args.append(shlex.quote(vm.filter))
            launcher = self._send_script(
                vm.hostname,
                f"tcpdump_{vm.hostname}_{vm.iface}.sh",
                f"echo $$ > {pidfile}\nexec tcpdump {' '.join(args)} 2> {errfile}\n",
            )

            utils.mm_cc_filter_vm(self.mm, vm.hostname)
            if vm.iface != "any":
                self.mm.cc_exec(f"ip link set {vm.iface} up")
            self.mm.cc_background(f"bash {launcher}")

        self.mm.clear_cc_filter()

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        if self.config.convert_to_json:
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
            self.mm.cc_exec(
                f"rm -f /dump-{vm.iface}.pcap {pidfile} /dump-{vm.iface}.err"
            )
            self.mm.clear_cc_filter()

            logger.info(f"done copying PCAP file from node {vm.hostname}")

            if self.config.convert_to_json:
                logger.info(
                    f"starting PCAP --> JSON conversion for node {vm.hostname}..."
                )

                if self._convert(pcap_out, json_out):
                    logger.info(
                        f"PCAP --> JSON conversion for node {vm.hostname} complete"
                    )

        logger.info(f"Stopped user component: {self.name}")

    def _send_script(self, hostname: str, name: str, body: str) -> str:
        """Send a script to the VM via cc; return its path there.

        Like the cc component: a script file is not subject to minimega's
        expansion of $name, which an inline command is.
        """

        src = Path(self.root_dir) / self.exp_name / name
        src.write_text("#!/bin/bash\n" + body)
        try:
            utils.mm_cc_send_wait(self.mm, hostname, str(src), self.exp_name)
        finally:
            self.mm.clear_cc_filter()
            src.unlink(missing_ok=True)

        return f"/tmp/miniccc/files/{self.exp_name}/{name}"

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

        app = self.extract_app("scorch")
        assert app is not None
        scorch = app.get("metadata") or {}
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
