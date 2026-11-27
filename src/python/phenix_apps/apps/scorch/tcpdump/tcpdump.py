import subprocess
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
)
from phenix_apps.apps.scorch.tcpdump import guest
from phenix_apps.apps.scorch.tcpdump.guest import GuestFilter, GuestOptions
from phenix_apps.common.logger import logger

# Deprecated: the pcap component captures with tcpdump too (method: tcpdump).
# Kept so existing scenarios run unchanged.


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

        logger.warning(
            "the tcpdump component is deprecated; use the pcap component with "
            "method: tcpdump"
        )
        self._check_stage_lists()

        for vm in self.config.vms:
            guest.start_capture(self, vm.hostname, vm.iface, vm.options, vm.filter)

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

            guest.stop_capture(self, vm.hostname, vm.iface, pcap_out)

            if self.config.convert_to_json:
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
