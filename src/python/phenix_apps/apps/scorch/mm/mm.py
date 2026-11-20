import os
import re
import subprocess
import time
from pathlib import Path
from typing import Annotated, Any, Final, Literal

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
    Name,
    PositiveSeconds,
    Token,
)
from phenix_apps.common import mmcapture, utils
from phenix_apps.common.logger import logger

# The filter is wrapped in single quotes, so it may hold spaces but no quotes,
# backslashes, '#' or line breaks (the rule of utils._validate_mm_filter).
Filter = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, pattern=r"""^[^'"\\#\r\n]+$"""
    ),
]
# A VM name or minimega target (vm[1-3], a,b, *) spliced into a raw minimega
# command: one word, with the characters minimega's lexer would read as
# syntax refused (the rule of utils._validate_mm_token).
Target = Annotated[str, Field(pattern=r"""^[^\s'"#\\]+$""")]
# A bare file name: no directory part.
FILENAME_PATTERN: Final[str] = r"^[A-Za-z0-9._:+-]+$"
Filename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=FILENAME_PATTERN),
]
# an interface index (or name) or a VLAN id (or name)
Index = NonNegativeInt | Interface
VlanId = int | Token


# Each command type gets its own model holding only the fields it uses, so a
# stray key the command never read (a filename on stop_capture, say) is only
# warned about, as it always was ignored.


CaptureFormat = Literal["pcap", "pcapng"]


def _format_of(cap: Any) -> CaptureFormat:
    """The format of a capture: `format`, else the one the file name says."""

    if cap.format:
        return cap.format
    return "pcapng" if (cap.filename or "").lower().endswith(".pcapng") else "pcap"


class CaptureFile(MetadataBlock):
    filename: Filename | None = None
    filter: Filter | None = None
    snaplen: NonNegativeInt | None = None
    # unset: pcapng for a .pcapng file name, else pcap; pcapng needs minimega 3.4.0
    format: CaptureFormat | None = None

    @model_validator(mode="after")
    def _format_matches_filename(self) -> "CaptureFile":
        name = (self.filename or "").lower()
        if self.format == "pcap" and name.endswith(".pcapng"):
            raise ValueError("format: pcap, but filename ends in .pcapng")
        if self.format == "pcapng" and name.endswith(".pcap"):
            raise ValueError("format: pcapng, but filename ends in .pcap")
        return self


class StartBridgeCapture(CaptureFile):
    bridge: Interface


class StopBridgeCapture(MetadataBlock):
    bridge: Interface
    convert: bool = False


class StartNamespaceCapture(CaptureFile):
    # unset: every VLAN of the experiment except MGMT
    vlans: Annotated[list[Name], Field(min_length=1)] | None = None
    # unset: every VM
    vms: Annotated[list[Hostname], Field(min_length=1)] | None = None
    bridges: Annotated[list[Interface], Field(min_length=1)] | None = None


class StopNamespaceCapture(MetadataBlock):
    convert: bool = False


class BridgeStartCapture(MetadataBlock):
    type: Literal["start_capture"]
    capture: StartBridgeCapture


class BridgeStopCapture(MetadataBlock):
    type: Literal["stop_capture"]
    capture: StopBridgeCapture


class NamespaceStartCapture(MetadataBlock):
    type: Literal["start_namespace_capture"]
    capture: StartNamespaceCapture = Field(default_factory=StartNamespaceCapture)


class NamespaceStopCapture(MetadataBlock):
    type: Literal["stop_namespace_capture"]
    capture: StopNamespaceCapture = Field(default_factory=StopNamespaceCapture)


BridgeCommand = Annotated[
    BridgeStartCapture
    | BridgeStopCapture
    | NamespaceStartCapture
    | NamespaceStopCapture,
    Field(discriminator="type"),
]


class Connect(MetadataBlock):
    interface: Index
    vlan: VlanId
    bridge: Interface | None = None


class Disconnect(MetadataBlock):
    interface: Index


class StartVMCapture(CaptureFile):
    interface: Index


class StopVMCapture(MetadataBlock):
    # stop only this interface's capture; unset stops every capture on the VM
    interface: Index | None = None
    convert: bool = False


class VMPower(MetadataBlock):
    type: Literal["start", "stop"]


class VMConnect(MetadataBlock):
    type: Literal["connect"]
    connect: Connect


class VMDisconnect(MetadataBlock):
    type: Literal["disconnect"]
    disconnect: Disconnect


class VMStartCapture(MetadataBlock):
    type: Literal["start_capture"]
    capture: StartVMCapture


class VMStopCapture(MetadataBlock):
    type: Literal["stop_capture"]
    capture: StopVMCapture | None = None


VMCommand = Annotated[
    VMPower | VMConnect | VMDisconnect | VMStartCapture | VMStopCapture,
    Field(discriminator="type"),
]


Stage = Literal["configure", "start", "stop", "cleanup"]
STAGES: tuple[Stage, ...] = ("configure", "start", "stop", "cleanup")
_TIME_SAMPLE = "2000-01-01T00:00:00Z"
_LIST_KEYS = {"configure", "start", "stop", "cleanup", "vms"}


def _nulls_to_lists(data: Any) -> Any:
    # an empty `stop:` in YAML is null; take it as "nothing to do"
    if isinstance(data, dict):
        return {k: [] if v is None and k in _LIST_KEYS else v for k, v in data.items()}
    return data


class VM(MetadataBlock):
    @model_validator(mode="before")
    @classmethod
    def _null_lists(cls, data: Any) -> Any:
        return _nulls_to_lists(data)

    # a minimega VM target: a name, or a pattern such as vm[1-3] or a,b
    hostname: Target
    configure: list[VMCommand] = Field(default_factory=list)
    start: list[VMCommand] = Field(default_factory=list)
    stop: list[VMCommand] = Field(default_factory=list)
    cleanup: list[VMCommand] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_capture_names(self) -> "VM":
        # The default name is built from the hostname, so a pattern such as
        # vm[1-3] fails at run time, maybe after earlier commands changed the
        # experiment. Fail it up front.
        for stage in STAGES:
            for cmd in getattr(self, stage):
                if cmd.type == "start_capture" and not cmd.capture.filename:
                    _capture_file(
                        f"{self.hostname}-{cmd.capture.interface}-{_TIME_SAMPLE}",
                        _format_of(cmd.capture),
                        default=True,
                    )
        return self


class MMMetadata(BaseModel):
    """Metadata for the mm component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    configure: list[BridgeCommand] = Field(default_factory=list)
    start: list[BridgeCommand] = Field(default_factory=list)
    stop: list[BridgeCommand] = Field(default_factory=list)
    cleanup: list[BridgeCommand] = Field(default_factory=list)
    vms: list[VM] = Field(default_factory=list)
    # seconds between checks that the captures reached the head node
    transfer_poll_interval: PositiveSeconds = 2
    # seconds to wait for the captures to reach the head node, and for each
    # tshark conversion; conversion is post-processing, so a timeout is logged
    convert_timeout: PositiveSeconds = 600

    @model_validator(mode="before")
    @classmethod
    def _null_lists(cls, data: Any) -> Any:
        return _nulls_to_lists(data)


def _capture_file(
    name: str, fmt: CaptureFormat | None = None, *, default: bool = False
) -> str:
    """A capture file name with `.pcap` (`.pcapng` for pcapng) added. A default
    name built from a VM target (vm[1-3]) can hold characters the run folder and
    conversion shell must not see, so it is refused instead of rewritten."""

    ext = ".pcapng" if fmt == "pcapng" else ".pcap"
    name = name if name.lower().endswith(ext) else f"{name}{ext}"
    if default and not re.fullmatch(FILENAME_PATTERN, name):
        raise ValueError(
            f"default capture file name {name!r} has characters outside "
            "letters, digits and . _ : + -; set capture.filename"
        )
    return name


def _set_capture_options(mm, cap: StartBridgeCapture | StartVMCapture) -> None:
    if cap.filter:
        # minimega reads the filter as one argument only when quoted
        mm.capture_pcap_filter(f"'{utils._validate_mm_filter(cap.filter)}'")
    if cap.snaplen:
        mm.capture_pcap_snaplen(cap.snaplen)


def _reset_capture_options(mm) -> None:
    # The filter and snaplen are namespace-wide and copied into each capture
    # when it starts. With no argument these commands only print the current
    # value, so clear them explicitly: a match-all filter, and snaplen 0, which
    # minimega reads as its 1600-byte default. The filter cannot be "": phenix
    # runs commands under "namespace <ns>", which rebuilds the command text and
    # drops the empty argument, so the old filter would stick.
    mm.capture_pcap_filter("'len >= 0'")
    mm.capture_pcap_snaplen(0)


class MM(ComponentBase):
    metadata_model = MMMetadata
    config: MMMetadata

    def __init__(self):
        ComponentBase.__init__(self, "mm")

        self.execute_stage()

    def configure(self):
        self.__run("configure")

    def start(self):
        self.__run("start")

    def stop(self):
        self.__run("stop")

    def cleanup(self):
        self.__run("cleanup")

    def __run(self, stage: Stage) -> None:
        mm = self.mm
        self._warn_unstopped_captures(stage)
        self._check_support(stage)

        for cmd in getattr(self.config, stage):
            cap = cmd.capture

            if cmd.type == "start_namespace_capture":
                self._start_namespace_capture(cap)
            elif cmd.type == "stop_namespace_capture":
                self._stop_namespace_capture(cap)
            elif cmd.type == "start_capture":
                self._start_bridge_capture(cap)
            else:  # stop_capture
                bridge = cap.bridge
                try:
                    logger.info(f"stopping pcap capture on bridge {bridge}")
                    self._stop_bridge_capture(bridge)
                    logger.info(f"stopped pcap capture on bridge {bridge}")

                    self._collect_captures(cap.convert)
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to stop pcap capture on bridge {bridge}: {ex}"
                    ) from ex

        for vm in self.config.vms:
            host = vm.hostname

            for vcmd in getattr(vm, stage):
                if vcmd.type == "start":
                    try:
                        logger.info(f"starting VM {host}")
                        mm.vm_start(host)
                        logger.info(f"started VM {host}")
                    except Exception as ex:
                        raise RuntimeError(f"unable to start vm {host}: {ex}") from ex
                elif vcmd.type == "stop":
                    try:
                        logger.info(f"stopping VM {host}")
                        mm.vm_stop(host)
                        logger.info(f"stopped VM {host}")
                    except Exception as ex:
                        raise RuntimeError(f"unable to stop vm {host}: {ex}") from ex
                elif vcmd.type == "connect":
                    conn = vcmd.connect
                    iface, vlan = str(conn.interface), str(conn.vlan)

                    utils._validate_mm_token(str(iface))
                    utils._validate_mm_token(str(vlan))
                    if conn.bridge:
                        utils._validate_mm_token(conn.bridge)

                    try:
                        logger.info(
                            f"connecting interface {iface} on {host} to VLAN {vlan}"
                        )
                        mm.vm_net_connect(host, iface, vlan, conn.bridge)
                        logger.info(
                            f"connected interface {iface} on {host} to VLAN {vlan}"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to connect interface {iface} on {host} to VLAN {vlan}: {ex}"
                        ) from ex
                elif vcmd.type == "disconnect":
                    disc = vcmd.disconnect
                    iface = str(disc.interface)

                    utils._validate_mm_token(str(iface))

                    try:
                        logger.info(f"disconnecting interface {iface} on {host}")
                        mm.vm_net_disconnect(host, iface)
                        logger.info(f"disconnected interface {iface} on {host}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to disconnect interface {iface} on {host}: {ex}"
                        ) from ex
                elif vcmd.type == "start_capture":
                    self._start_vm_capture(host, vcmd.capture)
                else:  # stop_capture
                    try:
                        logger.info(f"stopping pcap capture(s) on VM {host}")
                        cap = vcmd.capture
                        iface = None if cap is None else cap.interface
                        reply = mm.capture_pcap_delete_vm(host, iface)
                        mmcapture.check_final(mmcapture.rows(reply))
                        logger.info(f"stopped pcap capture(s) on VM {host}")

                        self._collect_captures(cap.convert if cap else False)
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop pcap capture(s) on vm {host}: {ex}"
                        ) from ex

    def _check_support(self, stage: Stage) -> None:
        """Fail before any command runs when the stage needs minimega 3.4.0 and
        the nodes have an older one."""

        needs: list[str] = []

        def note(cmd: Any) -> None:
            if cmd.type in ("start_namespace_capture", "stop_namespace_capture"):
                needs.append(cmd.type)
            elif cmd.type == "start_capture" and _format_of(cmd.capture) == "pcapng":
                needs.append("format: pcapng")

        for cmd in getattr(self.config, stage):
            note(cmd)
        for vm in self.config.vms:
            for vcmd in getattr(vm, stage):
                note(vcmd)

        if needs:
            self.capture_support().require(needs[0])

    def _scope(self) -> Path:
        """The folder of this component's runs. Every capture it starts writes below."""

        return self.base_dir.parent

    def _options(
        self,
        cap: Any,
        fmt: CaptureFormat,
        **selection: Any,
    ) -> str | None:
        return mmcapture.capture_options(
            filter=cap.filter, snaplen=cap.snaplen, format=fmt, **selection
        )

    def _start_bridge_capture(self, cap: StartBridgeCapture) -> None:
        bridge, fmt = cap.bridge, _format_of(cap)
        now = utils.utc_now()
        filename = _capture_file(
            cap.filename or f"{bridge}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
            fmt,
            default=not cap.filename,
        )
        path = str(Path(self.base_dir) / filename)
        modern = self.capture_support().available

        try:
            if modern:
                options = self._options(cap, fmt)
                logger.info(f"starting pcap capture for bridge {bridge}")
                self.mm.capture_pcap_bridge(bridge, path, option=options)
            else:
                _set_capture_options(self.mm, cap)
                try:
                    logger.info(f"starting pcap capture for bridge {bridge}")
                    self._make_run_folder()
                    self.mm.capture_pcap_bridge(bridge, path)
                finally:
                    _reset_capture_options(self.mm)
            logger.info(f"started pcap capture for bridge {bridge}")
        except Exception as ex:
            raise RuntimeError(
                f"unable to start pcap capture for bridge {bridge}: {ex}"
            ) from ex

    def _make_run_folder(self) -> None:
        # minimega before 3.4.0 does not create the folder on the other hosts
        self.mm.mesh_send(
            "all", f"shell mkdir -p {utils._validate_mm_token(str(self.base_dir))}"
        )

    def _stop_bridge_capture(self, bridge: str) -> None:
        if not self.capture_support().available:
            self.mm.capture_pcap_delete_bridge(bridge)
            return

        # a bridge has no other owner marker, so use the folder it writes to
        ours = [
            row
            for row in mmcapture.rows(self.mm.capture())
            if row.get("bridge") == bridge
            and row.get("type") == "pcap"
            and not row.get("interface")
            and mmcapture.is_under(row, self._scope())
        ]
        if not ours:
            raise RuntimeError(f"no pcap capture of this component on bridge {bridge}")

        self._delete_by_id(ours)

    def _delete_by_id(self, ours: list[dict[str, str]]) -> None:
        final = []
        for row in ours:
            final.extend(mmcapture.rows(self.mm.capture_pcap_delete_id(row["id"])))
        mmcapture.check_final(final or ours)

    def _start_vm_capture(self, host: str, cap: StartVMCapture) -> None:
        iface, fmt = str(cap.interface), _format_of(cap)

        utils._validate_mm_token(iface)

        now = utils.utc_now()
        filename = _capture_file(
            cap.filename or f"{host}-{iface}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
            fmt,
            default=not cap.filename,
        )
        path = os.path.join(self.base_dir, filename)
        modern = self.capture_support().available

        try:
            logger.info(f"starting pcap capture for interface {iface} on {host}")
            if modern:
                self.mm.capture_pcap_vm(
                    host, iface, path, option=self._options(cap, fmt)
                )
            else:
                _set_capture_options(self.mm, cap)
                try:
                    self._make_run_folder()
                    self.mm.capture_pcap_vm(host, iface, path)
                finally:
                    _reset_capture_options(self.mm)
            logger.info(f"started pcap capture for interface {iface} on {host}")
        except Exception as ex:
            raise RuntimeError(
                f"unable to start pcap capture for interface {iface} on {host}: {ex}"
            ) from ex

    def _start_namespace_capture(self, cap: StartNamespaceCapture) -> None:
        fmt = _format_of(cap)
        now = utils.utc_now()
        filename = _capture_file(
            cap.filename or f"{self.exp_name}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
            fmt,
            default=not cap.filename,
        )
        vlans = mmcapture.namespace_vlans(cap.vlans, self.experiment.status.vlans)

        try:
            options = self._options(
                cap, fmt, vlans=vlans, vms=cap.vms or (), bridges=cap.bridges or ()
            )
            logger.info(f"starting pcap capture for the namespace on VLANs {vlans}")
            self.mm.capture_pcap_namespace(
                str(Path(self.base_dir) / filename), option=options
            )
            logger.info("started pcap capture for the namespace")
        except Exception as ex:
            raise RuntimeError(
                f"unable to start pcap capture for the namespace: {ex}"
            ) from ex

    def _stop_namespace_capture(self, cap: StopNamespaceCapture) -> None:
        try:
            logger.info("stopping pcap capture(s) for the namespace")
            ours = [
                row
                for row in mmcapture.rows(self.mm.capture_pcap_namespace())
                if not row.get("host") and mmcapture.is_under(row, self._scope())
            ]
            if not ours:
                raise RuntimeError("no namespace capture of this component is running")

            final: list[dict[str, str]] = []
            for row in ours:
                reply = mmcapture.rows(self.mm.capture_pcap_delete_namespace(row["id"]))
                final.extend(r for r in reply if not r.get("host"))
            mmcapture.check_final(final or ours)
            logger.info("stopped pcap capture(s) for the namespace")

            # the head node wrote the files, so there is nothing to transfer
            self._collect_captures(cap.convert, transfer=False)
        except Exception as ex:
            raise RuntimeError(
                f"unable to stop pcap capture(s) for the namespace: {ex}"
            ) from ex

    def _warn_unstopped_captures(self, stage: Stage) -> None:
        """Warn about a start_capture in this stage with no stop_capture for the
        same bridge or VM interface after it, in this or a later stage. It is
        only a warning: leaving a capture running may be intended."""

        # (target, interface, is_start) in execution order
        events: list[tuple[str, str | None, bool]] = []
        starts: list[int] = []  # positions of this stage's starts

        for name in STAGES[STAGES.index(stage) :]:
            for cmd in getattr(self.config, name):
                is_start = cmd.type.startswith("start_")
                if name == stage and is_start:
                    starts.append(len(events))
                target = (
                    "the namespace"
                    if cmd.type.endswith("_namespace_capture")
                    else f"bridge {cmd.capture.bridge}"
                )
                events.append((target, None, is_start))
            for vm in self.config.vms:
                for vcmd in getattr(vm, name):
                    if vcmd.type not in ("start_capture", "stop_capture"):
                        continue
                    is_start = vcmd.type == "start_capture"
                    iface = None if vcmd.capture is None else vcmd.capture.interface
                    if name == stage and is_start:
                        starts.append(len(events))
                    events.append(
                        (
                            f"VM {vm.hostname}",
                            None if iface is None else str(iface),
                            is_start,
                        )
                    )

        for pos in starts:
            target, iface, _ = events[pos]
            stopped = any(
                not is_start and t == target and i in (None, iface)
                for t, i, is_start in events[pos + 1 :]
            )
            if not stopped:
                where = target if iface is None else f"{target} interface {iface}"
                logger.warning(
                    f"pcap capture on {where} started in stage '{stage}' has no "
                    "later stop_capture, so it keeps running after the run"
                )

    def _collect_captures(self, convert: bool, transfer: bool = True) -> None:
        """Pull the captures back to the head node, converting them if asked."""

        mm = self.mm
        if transfer:
            mm.file_get(os.path.relpath(self.base_dir, self.root_dir))

        if not convert:
            return

        # Conversion is post-processing: failures are logged, not raised.
        try:
            self._convert(mm, transfer)
        except Exception as ex:
            logger.error(f"PCAP --> JSON conversion failed: {ex}")

    def _wait_for_transfer(self, mm, timeout: float) -> bool:
        """Wait until the captures reach the head node; False on timeout."""

        logger.info("Waiting for transfer of pcap files to head node to complete.")
        deadline = time.monotonic() + timeout
        while True:
            time.sleep(self.config.transfer_poll_interval)

            if all(len(host["Tabular"]) == 0 for host in mm.file_status()):
                logger.info("Transfer of pcap files to head node has completed.")
                return True

            if time.monotonic() > deadline:
                logger.error(
                    f"pcap transfer to head node not done after {timeout}s; "
                    "skipping PCAP --> JSON conversion"
                )
                return False

    def _running_paths(self, mm) -> set[str]:
        """The files that running captures write."""

        resps = list(mm.capture() or [])
        if self.capture_support().available:
            resps += mm.capture_pcap_namespace() or []

        return {row["path"] for row in mmcapture.rows(resps) if row.get("path")}

    def _convert(self, mm, transfer: bool = True) -> None:
        timeout = self.config.convert_timeout

        if transfer and not self._wait_for_transfer(mm, timeout):
            return

        # a capture still running is incomplete; it is converted after its stop
        running = self._running_paths(mm)

        # convert pcap files not already converted
        for file in sorted(os.listdir(self.base_dir)):
            pcap_in = os.path.join(self.base_dir, file)
            json_out = f"{pcap_in}.jsonl"

            if not file.endswith((".pcap", ".pcapng")) or os.path.exists(json_out):
                continue
            if pcap_in in running:
                logger.info(
                    f"skipping PCAP --> JSON conversion of {file}: still running"
                )
                continue

            logger.info(f"starting PCAP --> JSON conversion of {file}")
            partial = f"{json_out}.part"

            try:
                with open(partial, "wb") as out:
                    result = subprocess.run(
                        ["tshark", "-r", pcap_in, "-T", "ek"],
                        stdout=out,
                        stderr=subprocess.DEVNULL,
                        timeout=timeout,
                    )
                if result.returncode != 0:
                    raise RuntimeError(f"tshark exited with status {result.returncode}")
                os.replace(partial, json_out)  # only a finished file is published
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as ex:
                logger.error(f"PCAP --> JSON conversion of {file} failed: {ex}")
                Path(partial).unlink(missing_ok=True)
                continue

            logger.info(f"PCAP --> JSON conversion of {file} complete")


def main():
    MM()


if __name__ == "__main__":
    main()
