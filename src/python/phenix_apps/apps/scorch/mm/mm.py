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
    Interface,
    MetadataBlock,
    PositiveSeconds,
    Token,
)
from phenix_apps.common import utils
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


class StartBridgeCapture(MetadataBlock):
    bridge: Interface
    filename: Filename | None = None
    filter: Filter | None = None
    snaplen: NonNegativeInt | None = None


class StopBridgeCapture(MetadataBlock):
    bridge: Interface
    convert: bool = False


class BridgeStartCapture(MetadataBlock):
    type: Literal["start_capture"]
    capture: StartBridgeCapture


class BridgeStopCapture(MetadataBlock):
    type: Literal["stop_capture"]
    capture: StopBridgeCapture


BridgeCommand = Annotated[
    BridgeStartCapture | BridgeStopCapture, Field(discriminator="type")
]


class Connect(MetadataBlock):
    interface: Index
    vlan: VlanId
    bridge: Interface | None = None


class Disconnect(MetadataBlock):
    interface: Index


class StartVMCapture(MetadataBlock):
    interface: Index
    filename: Filename | None = None
    filter: Filter | None = None
    snaplen: NonNegativeInt | None = None


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


def _capture_file(name: str, *, default: bool = False) -> str:
    """A capture file name with `.pcap` added. A default name built from a VM
    target (vm[1-3]) can hold characters the run folder and conversion shell
    must not see, so it is refused instead of rewritten."""

    name = name if name.lower().endswith(".pcap") else f"{name}.pcap"
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

        for cmd in getattr(self.config, stage):
            # TODO: ensure bridge capture gets run on each namespace host
            cap = cmd.capture
            bridge = cap.bridge

            if cmd.type == "start_capture":
                now = utils.utc_now()
                filename = _capture_file(
                    cap.filename or f"{bridge}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
                    default=not cap.filename,
                )

                _set_capture_options(mm, cap)

                try:
                    logger.info(f"starting pcap capture for bridge {bridge}")
                    mm.mesh_send(
                        "all",
                        f"shell mkdir -p {utils._validate_mm_token(str(self.base_dir))}",
                    )
                    mm.capture_pcap_bridge(bridge, str(Path(self.base_dir) / filename))
                    logger.info(f"started pcap capture for bridge {bridge}")
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to start pcap capture for bridge {bridge}: {ex}"
                    ) from ex
                finally:
                    _reset_capture_options(mm)
            else:  # stop_capture
                try:
                    logger.info(f"stopping pcap capture on bridge {bridge}")
                    mm.capture_pcap_delete_bridge(bridge)
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
                    cap = vcmd.capture
                    iface = str(cap.interface)

                    utils._validate_mm_token(str(iface))

                    now = utils.utc_now()
                    filename = _capture_file(
                        cap.filename or f"{host}-{iface}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
                        default=not cap.filename,
                    )

                    _set_capture_options(mm, cap)

                    try:
                        logger.info(
                            f"starting pcap capture for interface {iface} on {host}"
                        )
                        mm.mesh_send(
                            "all",
                            f"shell mkdir -p {utils._validate_mm_token(str(self.base_dir))}",
                        )
                        mm.capture_pcap_vm(
                            host, iface, os.path.join(self.base_dir, filename)
                        )
                        logger.info(
                            f"started pcap capture for interface {iface} on {host}"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to start pcap capture for interface {iface} on {host}: {ex}"
                        ) from ex
                    finally:
                        _reset_capture_options(mm)
                else:  # stop_capture
                    try:
                        logger.info(f"stopping pcap capture(s) on VM {host}")
                        cap = vcmd.capture
                        iface = None if cap is None else cap.interface
                        mm.capture_pcap_delete_vm(host, iface)
                        logger.info(f"stopped pcap capture(s) on VM {host}")

                        self._collect_captures(cap.convert if cap else False)
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop pcap capture(s) on vm {host}: {ex}"
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
                if name == stage and cmd.type == "start_capture":
                    starts.append(len(events))
                events.append(
                    (f"bridge {cmd.capture.bridge}", None, cmd.type == "start_capture")
                )
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

    def _collect_captures(self, convert: bool) -> None:
        """Pull the captures back to the head node, converting them if asked."""

        mm = self.mm
        mm.file_get(os.path.relpath(self.base_dir, self.root_dir))

        if not convert:
            return

        # Conversion is post-processing: failures are logged, not raised.
        try:
            self._convert(mm)
        except Exception as ex:
            logger.error(f"PCAP --> JSON conversion failed: {ex}")

    def _convert(self, mm) -> None:
        timeout = self.config.convert_timeout
        logger.info("Waiting for transfer of pcap files to head node to complete.")

        # wait for file transfer back to head node to be done
        deadline = time.monotonic() + timeout
        while True:
            time.sleep(self.config.transfer_poll_interval)

            done = all(len(host["Tabular"]) == 0 for host in mm.file_status())
            if done:
                break

            if time.monotonic() > deadline:
                logger.error(
                    f"pcap transfer to head node not done after {timeout}s; "
                    "skipping PCAP --> JSON conversion"
                )
                return

        logger.info("Transfer of pcap files to head node has completed.")

        # a capture still running is incomplete; it is converted after its stop
        running = {row[-1] for host in mm.capture() for row in host["Tabular"]}

        # convert pcap files not already converted
        for file in sorted(os.listdir(self.base_dir)):
            pcap_in = os.path.join(self.base_dir, file)
            json_out = f"{pcap_in}.jsonl"

            if not file.endswith(".pcap") or os.path.exists(json_out):
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
