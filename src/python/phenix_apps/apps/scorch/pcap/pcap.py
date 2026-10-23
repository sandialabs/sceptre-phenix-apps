import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any, Self

from box import Box
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

MATCH_ALL_BPF = "len >= 0"

# TODO: bridge capture functionality from mm.py component
# The issue with bridge captures in phenix is it will capture MGMT traffic,
# which includes traffic from providers to simulators and bennu field devices.
# The workaround for this could be to apply a filter with "capture pcap filter"
# that excludes the IP address ranges used by MGMT and any other undesirable VLANs.
# To work around issues with multiple experiments, the 'bridge-mode' argument
# to phenix can be leveraged.

# TODO: pcap file retrieval functionality from mm.py component (this assumes one node)
# TODO: netflow capture
# TODO: allow tcpdump and/or tshark to be used instead of minimega api


# minimega needs the filter wrapped in single quotes, and re-lexes it on the
# way to each host, so no quotes, backslashes, '#' or line breaks (the same
# rule as utils._validate_mm_filter)
Bpf = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^'\"\\#\r\n]*$"),
]


class VM(MetadataBlock):
    hostname: Hostname
    # an index into the node's interfaces, or an interface name
    interface: Interface | NonNegativeInt = 0
    # override the component-wide filter and snaplen for this VM
    filter: Bpf | None = None
    snaplen: NonNegativeInt | None = None


class PCAPMetadata(BaseModel):
    """Metadata for the pcap component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    vms: Annotated[list[VM], Field(min_length=1)]
    filter: Bpf | None = None
    snaplen: NonNegativeInt | None = None
    convert_to_json: bool = False
    create_merged_pcap: bool = False
    dedupe: bool = True
    merge_timeout: PositiveSeconds = 60.0  # mergecap and editcap
    tshark_timeout: PositiveSeconds = 120.0  # DoS fragment splitting

    @model_validator(mode="before")
    @classmethod
    def _convert_to_json_alias(cls, data: Any) -> Any:
        """`convertToJSON` is the deprecated name of `convert_to_json`."""

        if isinstance(data, dict) and "convertToJSON" in data:
            data = dict(data)
            old = data.pop("convertToJSON")
            logger.warning(
                "pcap: 'convertToJSON' is deprecated; rename it to 'convert_to_json'"
            )
            data.setdefault("convert_to_json", old)
        return data

    @model_validator(mode="after")
    def _check_vms(self) -> Self:
        seen = [(vm.hostname, str(vm.interface)) for vm in self.vms]
        if dupes := sorted({f"{h} {i}" for h, i in seen if seen.count((h, i)) > 1}):
            raise ValueError(
                f"vms: captured more than once: {', '.join(dupes)}; each capture "
                "writes the same file"
            )
        return self


class PCAP(ComponentBase):
    """
    Implements minimega's "capture pcap" API as a Scorch component.
    """

    metadata_model = PCAPMetadata
    config: PCAPMetadata

    def __init__(self):
        ComponentBase.__init__(self, "pcap")
        self._check_commands_available()
        self.execute_stage()

    def _check_commands_available(self):
        for command in ["tshark", "capinfos", "editcap", "mergecap"]:
            if not shutil.which(command):
                raise RuntimeError(
                    f"'{command}' is unavailable on this host, which is required for PCAP processing"
                )

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        self._check_run_order()
        for row in self._active_captures():
            logger.warning(
                f"another capture is active in this minimega namespace: {row}; "
                "clearing pcap captures to start ours will stop it. Do not run "
                "pcap alongside other capture components (mm, tcpdump, erspan)"
            )

        logger.info("clearing capture on minimega")
        self.mm.clear_capture("pcap")

        vms = self.config.vms
        logger.info(f"starting capture for {len(vms)} VMs")
        try:
            for i, vm in enumerate(vms):
                hostname, interface = self.get_host_and_iface(Box(vm.model_dump()))
                filepath = Path(self.base_dir, f"{hostname}-{interface}.pcap")

                self._set_capture_options(
                    vm.filter or self.config.filter,
                    self.config.snaplen if vm.snaplen is None else vm.snaplen,
                )
                logger.info(
                    f"starting capture on '{hostname}' interface '{interface}' to '{filepath}' ({i + 1} of {len(vms)})"
                )
                self.mm.capture_pcap_vm(hostname, interface, str(filepath))
        finally:
            # unset, so they do not apply to later captures in the namespace
            self._set_capture_options(None, None)

        logger.info(f"Started user component: {self.name}")

    def _set_capture_options(self, bpf: str | None, snaplen: int | None) -> None:
        """Set minimega's namespace-wide filter and snaplen, which it copies
        into each capture when the capture starts. None resets them: a match-all
        filter, and snaplen 0, which minimega reads as its 1600-byte default.
        (With no argument these commands only print the current value.)"""

        # Berkeley Packet Filter (BPF) syntax: https://biot.com/capstats/bpf.html
        # minimega reads the filter as one argument only when quoted
        # (minimega pkg/minicli/input.go).
        # The reset cannot be "": phenix runs commands under "namespace <ns>",
        # which rebuilds the command text and drops the empty argument, so
        # "capture pcap filter" only prints the current filter and the previous
        # VM's filter sticks. A match-all filter selects every packet, the same
        # as no filter, and always overwrites.
        if bpf:
            logger.info(f"applying pcap BPF filter: '{bpf}'")
        self.mm.capture_pcap_filter(
            f"'{utils._validate_mm_filter(bpf)}'" if bpf else f"'{MATCH_ALL_BPF}'"
        )
        # https://wiki.wireshark.org/SnapLen
        if snaplen:
            logger.info(f"applying pcap snaplen: {snaplen}")
        self.mm.capture_pcap_snaplen(snaplen or 0)

    def _check_run_order(self) -> None:
        app = self.extract_app("scorch")
        assert app is not None
        scorch = app.metadata
        for message in run_order_warnings(
            self.name, scorch.components, scorch.runs[self.run]
        ):
            logger.warning(message)

    def _active_captures(self) -> list[str]:
        """One string per capture minimega reports in this namespace."""

        return [
            " ".join(row)
            for resp in self.mm.capture() or []
            for row in resp.get("Tabular") or []
        ]

    def _stop_captures(self) -> tuple[list[Path], dict[str, str]]:
        """Stop the capture on each listed interface; return the capture files
        and which VM each came from, for the DoS special processing."""

        pcap_paths = []
        host_of: dict[str, str] = {}

        vms = self.config.vms
        logger.info(f"stopping captures for {len(vms)} VMs")
        for i, vm in enumerate(vms):
            hostname, interface = self.get_host_and_iface(Box(vm.model_dump()))

            logger.info(
                f"stopping PCAP capture on interface {interface} for VM {hostname} ({i + 1} of {len(vms)})"
            )
            # only this interface: other captures on the VM are not ours
            self.mm.capture_pcap_delete_vm(hostname, interface)

            pcap_path = Path(self.base_dir, f"{hostname}-{interface}.pcap")
            pcap_paths.append(pcap_path)
            host_of[pcap_path.name] = hostname

        # clearing also stops other components' captures, so only reset
        # minimega's filter and snaplen once nothing else is capturing
        if self._active_captures():
            logger.info("other captures are active, not clearing capture on minimega")
        else:
            logger.info("clearing capture on minimega")
            self.mm.clear_capture("pcap")

        return pcap_paths, host_of

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        self._check_run_order()

        pcap_paths, host_of = self._stop_captures()

        logger.info(f"verifying {len(pcap_paths)} PCAP files")
        pcap_metadata = {}
        for pcap_path in pcap_paths:
            if not pcap_path.is_file():
                raise RuntimeError(f"PCAP file doesn't exist: {pcap_path}")

            try:
                pcap_info = utils.pcap_capinfos(pcap_path)
            except Exception as ex:
                raise RuntimeError(
                    f"failed to run capinfos to verify on PCAP file {pcap_path}: {ex}"
                ) from ex

            # verify pcap files are valid by checking their metadata with capinfos
            if not pcap_info or "pcap" not in pcap_info["File type"]:
                raise RuntimeError(
                    f"failed validation of PCAP metadata for file {pcap_path}\nraw info: {pcap_info}"
                )

            pcap_metadata[pcap_path.name] = pcap_info

        # merge pcap files together into a single consolidated PCAP
        # the pcaps that were merged will be moved into "raw" sub-directory
        if self.config.create_merged_pcap:
            logger.info(
                f"merging {len(pcap_paths)} PCAP files into a single file (create_merged_pcap=true)"
            )

            merged_path = self._merge_pcaps(pcap_paths)

            # move all pcaps that were merged into "raw" sub-directory
            new_paths = []
            raw_dir = Path(self.base_dir, "raw")
            raw_dir.mkdir(exist_ok=True)
            for pcap_path in pcap_paths:
                new_path = Path(pcap_path.parent, "raw", pcap_path.name)
                pcap_path.rename(new_path)
                new_paths.append(new_path)

            pcap_paths = new_paths
            pcap_paths.append(merged_path)

            if self.config.dedupe:
                logger.info(
                    f"'dedupe' is true, removing duplicates from '{merged_path.name}'"
                )

                # special processing for TCP flood packets
                scorch = self.extract_app("scorch").metadata
                dos_targets = dos_targets_for_run(
                    scorch.components, scorch.runs[self.run]
                )

                if dos_targets:
                    logger.info("Performing special processing for TCP packet flood")
                    target_paths, non_target_paths = split_by_host(
                        [p for p in pcap_paths if p != merged_path],
                        host_of,
                        dos_targets,
                    )

                    # merge all hosts EXCEPT hosts targeted by DOS into merged.pcap, dedupe
                    logger.info(
                        f"Special processing: merging non-target PCAPs: {[p.name for p in non_target_paths]}"
                    )
                    # when every capture is a DoS target there is nothing to
                    # merge here; mergecap fails on an empty input list
                    base: list[Path] = []
                    if non_target_paths:
                        merged_path = self._merge_pcaps(non_target_paths)
                        self._dedupe_pcap(merged_path)
                        base = [merged_path]

                    # split each target's PCAP into two, first part has the DOS packets, second one has everything else
                    logger.info(
                        f"Special processing: splitting DOS packets from non-DOS packets for targets: {[p.name for p in target_paths]}"
                    )
                    non_dos = []
                    fragmented = []
                    for t_path in target_paths:
                        frag_path = t_path.with_stem(f"{t_path.stem}_fragmented")
                        # tshark gets tshark_timeout seconds
                        utils.run_command(
                            self._tshark_split(t_path, frag_path, "ip.frag_offset > 0"),
                            timeout=self.config.tshark_timeout,
                        )
                        fragmented.append(frag_path)

                        nd_path = t_path.with_stem(f"{t_path.stem}_no_dos_fragments")
                        # tshark gets tshark_timeout seconds
                        utils.run_command(
                            self._tshark_split(
                                t_path, nd_path, "not (ip.frag_offset > 0)"
                            ),
                            timeout=self.config.tshark_timeout,
                        )
                        non_dos.append(nd_path)

                    # merge the "everything else" pcaps from targets into merged.pcap, dedupe again
                    logger.info(
                        "Special processing: merging non-attack packets into merged.pcap and deduping"
                    )
                    # GAH, need to make sure pcap is merged into self
                    merged_path = self._merge_pcaps([*base, *non_dos])
                    self._dedupe_pcap(merged_path)

                    # merge the "dos packets" pcaps from targets into merged.pcap, DON'T dedupe this time
                    logger.info(
                        "Special processing: final merge of fragmented attack packets into merged.pcap"
                    )
                    merged_path = self._merge_pcaps([merged_path, *fragmented])

                    # delete the fragmented PCAPs (those with DOS packets)
                    logger.info(
                        "Special processing: deleting fragmented PCAPs (those with DOS packets)"
                    )
                    for wd_path in fragmented:
                        wd_path.unlink()
                    logger.info("Finished special processing for TCP packet flood")
                else:
                    self._dedupe_pcap(merged_path)
            else:
                logger.info(
                    f"NOT removing duplicates from '{merged_path.name}' (dedupe=false)"
                )

            pcap_metadata[merged_path.name] = utils.pcap_capinfos(merged_path)

        # Save metadata to JSON file
        m_path = Path(self.base_dir, "pcap_metadata.json")
        logger.info(f"saving pcap metadata to {m_path}")
        utils.write_json(m_path, pcap_metadata)

        # Process PCAPs to JSON, once all captures have been stopped
        if self.config.convert_to_json:
            logger.info(
                f"PCAP --> JSON conversion enabled, converting {len(pcap_paths)} files"
            )

            for pcap_path in pcap_paths:
                # load6-0.pcap -> load6-0.jsonl
                json_path = pcap_path.with_suffix(
                    ".jsonl"
                )  # .pcap.jsonl could break filters for "*.pcap*"
                logger.info(
                    f"running PCAP --> JSON conversion (source={pcap_path.name}, dest={json_path.name})"
                )
                with json_path.open("w") as json_file:
                    proc = subprocess.run(
                        ["tshark", "-r", str(pcap_path), "-T", "ek"],
                        stdout=json_file,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"PCAP --> JSON conversion of {pcap_path.name} failed: "
                        f"{proc.stderr.decode(errors='replace').strip()}"
                    )
        else:
            logger.info("PCAP --> JSON conversion disabled")

        logger.info(f"Stopped user component: {self.name}")

    def _merge_pcaps(
        self, pcap_paths: list[Path], merged_name: str = "merged.pcap"
    ) -> Path:
        merged_path = Path(self.base_dir, merged_name)

        overwriting = bool(merged_path in pcap_paths)
        if overwriting:
            merged_path = merged_path.with_stem("temp_merged")

        mergecap_cmd = ["mergecap", "-w", str(merged_path)]
        mergecap_cmd += [str(p) for p in pcap_paths]
        utils.run_command(
            mergecap_cmd, timeout=self.config.merge_timeout
        )  # this shouldn't take long

        if not merged_path.is_file():
            raise RuntimeError(
                f"PCAP merge failed, output file '{merged_path}' doesn't exist"
            )

        # rename "temp_merged.pcap" to "merged.pcap"
        if overwriting:
            merged_path = merged_path.replace(merged_path.with_name(merged_name))

        return merged_path

    @staticmethod
    def _tshark_split(src: Path, dst: Path, display_filter: str) -> list[str]:
        return [
            "tshark",
            "-r",
            str(src),
            "-w",
            str(dst),
            "-o",
            "ip.defragment:FALSE",
            "-o",
            "tcp.desegment_tcp_streams:FALSE",
            "-n",
            "-Y",
            display_filter,
        ]

    def _dedupe_pcap(self, pcap_path: Path) -> None:
        dd_path = Path(self.base_dir, "deduped.pcap")
        utils.run_command(
            ["editcap", "-d", str(pcap_path), str(dd_path)],
            timeout=self.config.merge_timeout,
        )

        if not dd_path.is_file():
            raise RuntimeError(
                f"PCAP dedupe failed, output file '{dd_path}' doesn't exist"
            )

        dd_path.replace(pcap_path)  # overwrite merged.pcap with deduped.pcap


def split_by_host(
    paths: list[Path], host_of: dict[str, str], hosts: list[str]
) -> tuple[list[Path], list[Path]]:
    """Split capture files into those from the given VMs and the rest.

    Matches the capture's VM exactly; testing the file name for the hostname
    would count load10's capture as one of load1's.
    """

    matched = [p for p in paths if host_of.get(p.name) in hosts]
    return matched, [p for p in paths if p not in matched]


def _loop_chain(run_config: Any) -> list[dict]:
    """The run's stage lists, then those of its loop, its loop's loop, and so on.

    `loop: null` ends the chain.
    """

    chain = []
    while isinstance(run_config, dict):
        chain.append(run_config)
        run_config = run_config.get("loop")
    return chain


def _stage_names(run_config: dict, stage: str | None = None) -> set[str]:
    return {
        n
        for level in _loop_chain(run_config)
        for key, names in level.items()
        if key != "loop" and stage in (None, key) and isinstance(names, list)
        for n in names
    }


def dos_targets_for_run(components: list, run_config: dict) -> list[str]:
    """Hostnames targeted by the first dos/cyber_physical disruption in this run.

    A component is in the run if its name is in any stage list of the run or of
    any of its nested loops; a disruption defined for another run does not count.
    """

    in_run = _stage_names(run_config)
    for comp in components:
        if (
            comp.type == "disruption"
            and comp.name in in_run
            and comp.metadata.current_disruption in ["dos", "cyber_physical"]
        ):
            return [t.hostname for t in comp.metadata.dos.targets]
    return []


def run_order_warnings(name: str, components: list, run_config: dict) -> list[str]:
    """Problems with where `name` sits in the run's stage lists."""

    warnings = []
    for stage in ("start", "stop"):
        if name not in _stage_names(run_config, stage):
            warnings.append(
                f"'{name}' is not in a '{stage}' stage list of this run; a capture "
                "needs both: start before the traffic you want, stop after it ends"
            )

    # a type may be omitted in the scenario, in which case it is the name
    collectors = {
        c.name for c in components if (c.get("type") or c.name) == "collector"
    }
    for level in _loop_chain(run_config):
        stop = level.get("stop")
        if isinstance(stop, list) and name in stop:
            early = [n for n in stop[: stop.index(name)] if n in collectors]
            if early:
                warnings.append(
                    f"collector {early} runs before '{name}' in a stop list, so it "
                    f"copies the captures before they are written; list '{name}' first"
                )
    return warnings


def main():
    PCAP()


if __name__ == "__main__":
    main()
