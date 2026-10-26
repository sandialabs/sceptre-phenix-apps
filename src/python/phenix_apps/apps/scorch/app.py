import difflib
import io
import json
import os
import re
import signal
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, ClassVar

import minimega
from box import Box
from elasticsearch import Elasticsearch
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from phenix_apps.common import utils
from phenix_apps.common.base import ExperimentBase
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger, phenix_stderr_sink
from phenix_apps.common.settings import PHENIX_DIR

# Metadata rules. Values are validated in pydantic's strict mode: a wrong type
# (the string "false" for a bool, "6" for an int) or a malformed value fails the
# stage, even in a field that is not used yet, so a config is either valid or
# rejected up front. Only an unknown key in a MetadataBlock, usually a typo, is
# a warning, logged with a did-you-mean hint.


def _hostname(value: str) -> str:
    try:
        return utils.validate_hostname(value)
    except AppError:
        raise ValueError(
            "not a valid hostname: 2 to 63 letters, digits and interior hyphens"
        ) from None


# Field types for metadata models. Names, interfaces and paths are interpolated
# into commands (minimega joins its arguments with spaces, treats `#` as a
# comment and `\` as an escape), so a Token is one word of plain characters:
# none of those, quotes, or shell syntax. Every sink of a Token today takes an
# argument vector (minimega's `shell`, miniccc, ovs-vsctl), so the allowlist is
# defense in depth, and it still holds `vm[1-3]`, `a,b` and `ns//vlan`.
# Args is free text for a command line that a shell may parse (inside a
# `bash -c '...'`, where minimega's lexer has already turned a backslash-n
# into a newline), so it is plain characters too: no quotes, backslashes or
# shell syntax. FilterExpr is for text that only ever reaches a program as
# arguments, never a shell: it also takes the `( ) [ ] ! & | < > ^` of a
# tcpdump filter. An empty Args or FilterExpr is valid.
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][\w.-]*$")]
Token = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+,=@/\[\]-]+$")]
Args = Annotated[str, Field(pattern=r"^[A-Za-z0-9_ .,:=@%/+-]*$")]
FilterExpr = Annotated[str, Field(pattern=r"^[A-Za-z0-9_ .,:=@%/+*()\[\]!&|<>^-]*$")]
# A topology node name, by phenix core's rules (utils.validate_hostname).
Hostname = Annotated[str, AfterValidator(_hostname)]
# A Linux interface name: at most 15 characters (IFNAMSIZ), no `/`, `:` or
# whitespace. phenix's schema leaves interface names unconstrained.
Interface = Annotated[str, Field(pattern=r"^[A-Za-z0-9_][\w.-]{0,14}$")]
# A file path on a Linux or Windows VM, with forward slashes (Windows accepts
# them; minimega would eat a backslash). No shell or cmd.exe metacharacters, so
# it is safe unquoted in `rm`, `del` or a minimega file command.
FilePath = Annotated[str, Field(pattern=r"^(?:[A-Za-z]:)?[\w./+@-]+$")]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class MetadataBlock(BaseModel):
    """A nested metadata block. Unknown keys are kept but warned about, since
    they are usually typos the old code silently ignored."""

    model_config = ConfigDict(extra="allow")


def _unknown_keys(model: BaseModel, path: str = "") -> list[str]:
    """Warnings for unknown keys in every MetadataBlock below model."""

    prefix = f"{path}." if path else ""
    found = []
    if isinstance(model, MetadataBlock):
        known = list(type(model).model_fields)
        for key in model.model_extra or {}:
            close = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
            hint = (
                f"did you mean '{close[0]}'?" if close else "known: " + ", ".join(known)
            )
            found.append(
                f"{prefix}{key}: unknown key, ignored. Fix: remove it ({hint})"
            )
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            found += _unknown_keys(value, f"{prefix}{name}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, BaseModel):
                    found += _unknown_keys(item, f"{prefix}{name}.{index}")
    return found


def validate_metadata[M: BaseModel](
    model: type[M], metadata: dict[str, Any] | None, component: str
) -> tuple[M, list[str]]:
    """Validate a component's metadata, returning the model and its warnings.

    Raises one ValueError listing every fatal problem. Field values are left
    out of messages so nothing sensitive reaches the status file or logs.
    """

    try:
        config = model.model_validate({} if metadata is None else metadata, strict=True)
    except ValidationError as ex:
        problems = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc']) or '(metadata)'}: {err['msg']}"
            for err in ex.errors()
        )
        raise ValueError(
            f"invalid metadata for component '{component}' "
            f"({ex.error_count()} problem(s)):\n{problems}"
        ) from None
    return config, _unknown_keys(config)


def parse_metadata[M: BaseModel](
    model: type[M], metadata: dict[str, Any] | None, component: str
) -> M:
    """validate_metadata, logging each warning against the component."""

    config, warnings = validate_metadata(model, metadata, component)
    for message in warnings:
        logger.warning(f"metadata warning for component '{component}': {message}")
    return config


class ComponentBase(ExperimentBase):
    """
    Base class for Scorch components.

    Developers must:
    1. Use `phenix_apps.common.logger` for logging.
    2. Raise exceptions (e.g. `ValueError`, `RuntimeError`) instead of calling `sys.exit()` for fatal errors.
       This ensures that the `execute_stage` method can catch the error, write the JSON status file, and log the traceback.
    """

    valid_stages = ("configure", "start", "stop", "cleanup")

    # Optional pydantic model for this component's metadata. When set,
    # execute_stage parses the metadata into self.config before the stage runs,
    # so a bad config fails the stage once, naming every bad field.
    metadata_model: ClassVar[type[BaseModel] | None] = None
    # A class-level default, not set in __init__: components without a model
    # keep reading self.metadata, and their own config attribute or property
    # must not be overwritten.
    config: BaseModel | None = None

    @classmethod
    def check_args(cls) -> None:
        """
        Validates command line arguments.
        Expects 5 arguments: <run_stage> <component_name> <run_id> <current_loop> <current_loop_count>
        """

        if len(sys.argv) != 6:
            raise ValueError(
                f"Invalid arguments passed to scorch component. "
                f"Must pass exactly five arguments: was passed {len(sys.argv) - 1}. "
                "Expects <run_stage> <component_name> <run_id> <current_loop> <current_loop_count> << <json_input>"
            )

        if sys.argv[1] not in cls.valid_stages:
            raise ValueError(
                f"{sys.argv[1]} is not a valid stage. Valid stages are: {cls.valid_stages}"
            )

    def __init__(self, typ: str) -> None:
        self.type: str = typ

        self.dryrun: bool = os.getenv("PHENIX_DRYRUN", "false") == "true"

        self.check_args()

        self.stage: str = sys.argv[
            1
        ]  # stage name, one of: configure, start, stop, cleanup
        self.name: str = sys.argv[
            2
        ]  # component name (name given to component by the user in the Scorch app configuration)
        self.run: int = int(
            sys.argv[3]
        )  # Run number, usually 0 unless multiple runs are defined in scenario
        self.loop: int = int(
            sys.argv[4]
        )  # Loop number, usually 0 unless loops are defined, then it's...always 1?
        self.count: int = int(
            sys.argv[5]
        )  # Run iteration, usually 0 unless "count: <num>" is specified (multiple iterations of same run or loop)

        # Keep this around just in case components want direct access to it.
        self.raw_input: str = sys.stdin.read()

        try:
            self.experiment: Box = Box.from_json(self.raw_input)
        except Exception as ex:
            raise ValueError(
                f"Failed to parse experiment JSON for scorch component '{self.name}': {ex}"
            ) from ex

        self.exp_name: str = self.experiment.spec.experimentName
        self.exp_dir: Path = Path(self.experiment.spec.baseDir)
        self.metadata: Box | None = self.extract_metadata()

        self.root_dir: Path = Path(PHENIX_DIR) / "images"
        self.files_dir: Path = Path(
            os.getenv("PHENIX_FILES_DIR", self.root_dir / self.exp_name / "files")
        )
        self.base_dir: Path = (
            self.files_dir
            / f"scorch/run-{self.run}/{self.name}/loop-{self.loop}-count-{self.count}"
        )

        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._mm: minimega.minimega | None = None  # minimega instance
        self._es: Elasticsearch | None = None  # Elasticsearch instance

        def signal_handler(_, __):
            pass

        # handle signals for backgrounded components
        signal.signal(signal.SIGTERM, signal_handler)

    def execute_stage(self) -> None:
        """
        Executes the stage passed in from the json blob and captures logger output, stdout, and stderr to info file.

        This method sets up:
        1. System Logging: Configures the logger to output structured JSON to stderr for the parent process to consume.
        2. Stdout/Stderr mirroring: Output is sent to the original streams (for UI/logging) AND captured in memory buffers.
        3. Log Capturing: A sink is added to the logger to capture all log records into a memory buffer.
           This ensures that logs (including those from libraries) are included in the final JSON status file.
        4. Exception Handling: Wraps execution in a try/except block. If an exception occurs (including those raised
           instead of sys.exit), it is logged with a traceback, and the JSON status file is written before re-raising.
        """

        stages_dict = {
            "configure": self.configure,
            "start": self.start,
            "stop": self.stop,
            "cleanup": self.cleanup,
        }

        orig_stdout_stream = sys.stdout
        orig_stderr_stream = sys.stderr
        log_buffer = io.StringIO()

        # mirror stdout and stderr
        stdout_mirror = _MirrorAndBuffer(orig_stdout_stream, io.StringIO())
        stderr_mirror = _MirrorAndBuffer(orig_stderr_stream, io.StringIO())

        log_format = "[{time:YYYY-MM-DD HH:mm:ss.SSS}] {level} : {message}"

        # Configure logger to output JSON to stderr while also mirroring log lines
        # to stdout so the scorch modal continues to receive component progress.
        # diagnose=False on every sink: a traceback must not render local
        # values, which can include metadata secrets such as an ssh password
        logger.remove()
        logger.add(phenix_stderr_sink, diagnose=False)
        ui_sink_id = logger.add(stdout_mirror, format=log_format, diagnose=False)

        # Add a sink to capture logs to the buffer for the status file
        sink_id = logger.add(
            lambda msg: log_buffer.write(msg), format=log_format, diagnose=False
        )

        start = time.time()

        # redirect stdout and stderr to mirror to our buffers
        error_occurred = False
        try:
            with redirect_stdout(stdout_mirror), redirect_stderr(stderr_mirror):
                # a stage the component does not implement never read metadata,
                # so a bad config must not fail it (cleanup especially)
                implemented = getattr(type(self), self.stage) is not getattr(
                    ComponentBase, self.stage
                )
                if self.metadata_model is not None and implemented:
                    self.config = parse_metadata(
                        self.metadata_model, self.metadata, self.name
                    )
                out = stages_dict[self.stage]() or ""
        except Exception as ex:
            error_occurred = True
            logger.exception(
                f"Error executing stage '{self.stage}' for component '{self.name}'"
            )
            out = f"Error occurred: {ex}"
        finally:
            sys.stdout = orig_stdout_stream
            sys.stderr = orig_stderr_stream
            logger.remove(ui_sink_id)
            logger.remove(sink_id)

        end = time.time()

        start_dt = datetime.fromtimestamp(start, tz=UTC)
        end_dt = datetime.fromtimestamp(end, tz=UTC)

        start_ts = start_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        end_ts = end_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # filenames can't have colons, so replace with dashes
        start_ts_filename = start_dt.strftime("%Y-%m-%dT%H-%M-%SZ")

        info_file = self.base_dir / f"{self.stage}-{start_ts_filename}.json"

        content = {
            "experiment_name": self.exp_name,
            "scorch_run_index": self.run,
            "component": self.name,
            "loop": self.loop,
            "count": self.count,
            "stage": self.stage,
            "start": start_ts,
            "end": end_ts,
            "return": out,
            "stdout": self._format_stream(stdout_mirror.getvalue()),
            "stderr": self._format_stream(stderr_mirror.getvalue()),
            "logs": self._format_stream(log_buffer.getvalue()),
        }
        with info_file.open("w") as f:
            json.dump(content, f, indent=2)

        if error_occurred:
            raise RuntimeError(f"Error occurred during stage execution: {out}")

    def _format_stream(self, s):
        if not s:
            return []
        return [ln.strip() for ln in s.splitlines() if ln.strip()]

    @property
    def es(self) -> Elasticsearch:
        """Connect to Elasticsearch and return the initialized object."""
        if not self._es:
            server = ((self.metadata or {}).get("elasticsearch") or {}).get("server")
            if not server:
                raise ValueError(
                    f"component '{self.name}': metadata.elasticsearch.server "
                    "is required to connect to Elasticsearch"
                )
            logger.info(f"Connecting to Elasticsearch: {server}")
            self._es = utils.connect_elastic(server)
        return self._es

    @es.setter
    def es(self, es: Elasticsearch) -> None:
        self._es = es

    def extract_metadata(self) -> Box | None:
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == "scorch":
                md = app.get("metadata", None)

                if not md:
                    return None

                for cmp in md.components:
                    # phenix core defaults an omitted or empty type to the name
                    ctype = cmp.get("type") or cmp.name
                    if cmp.name == self.name and ctype == self.type:
                        return cmp.get("metadata", None)
        return None

    def extract_run_name(self) -> str:
        md = self.extract_app("scorch").get("metadata") or {}
        runs = md.get("runs", [])

        if len(runs) <= self.run:
            return str(self.run)

        name = runs[self.run].get("name", str(self.run))

        # name might be an empty string...
        if not name:
            return str(self.run)

        name = str(name)

        # Callers put the name in the name of a file under the experiment's
        # directory on the host (cc, caldera), so a name that is not one plain
        # word (a '/', '..' or space in it) is replaced by the run's index.
        if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", name):
            logger.warning(
                f"run {self.run} has a name that is not a plain word, using "
                f"'{self.run}' in file names instead"
            )
            return str(self.run)

        return name

    def extract_app(self, name: str) -> Box:
        for app in self.experiment.spec.scenario.apps:
            if app.name == name:
                return app
        raise ValueError(f"failed to find app '{name}'")

    def get_host_and_iface(self, config: Box) -> tuple[str, int]:
        """
        Extract the hostname and interface fields from metadata, and resolve them on the node.
        The 'interface' field in the config can either be a index (0) or a name (eth0).
        The name must match the name of an interface on the nodes in the topology.

        Returns:
            tuple with the hostname and the interface index
        """
        hostname = config.get("hostname")
        if not hostname:
            raise ValueError(f"no hostname provided for VM config {config}")

        node = self.extract_node(hostname)
        if not node:
            raise ValueError(f'failed to find node "{hostname}" (config={config})')

        if not node.network.interfaces:
            raise ValueError(
                f"no interfaces defined for node {hostname}! (node={node}, config={config})"
            )

        # Default to interface 0
        interface = config.get("interface", 0)

        # If it's an integer, use as-is
        # If not, attempt to resolve the name to a index
        try:
            interface = int(interface)
        except ValueError:
            for idx, if_val in enumerate(node.network.interfaces):
                if if_val.name == interface:
                    interface = idx
                    break
            else:
                raise ValueError(
                    f"interface {interface} does not exist on node {hostname}"
                )

        return hostname, interface

    def recv_file(self, vm: str, src: list[str] | str, dst: str = "") -> None:
        if not dst and isinstance(src, str):
            dst = str(self.base_dir / Path(src).name)
        elif not dst and isinstance(src, list):
            dst = str(self.base_dir)

        logger.info(f"copying file from {vm} (src={src}, dst={dst})")

        try:
            utils.mm_recv(self.mm, vm, src, dst)
            logger.info(f"file '{src}' received from VM {vm} to {dst}")
        except Exception as ex:
            raise RuntimeError(
                f"error receiving file '{src}' from VM {vm}: {ex}"
            ) from ex

    def ensure_vm_running(self, vm: str) -> None:
        logger.info(f"Checking if VM is running (VM hostname: {vm})")
        vm_info = utils.mm_info_for_vm(self.mm, vm)
        if not vm_info or vm_info["state"].lower() != "running":
            raise RuntimeError(f"VM isn't running (vm name: {vm})")

    def run_and_check_command(
        self,
        vm: str,
        cmd: str,
        timeout: float = 5.0,
        poll_rate: float = 0.5,
        debug: bool = False,
    ) -> dict:
        """
        Run and wait for command, and if exit code is non-zero, print error and exit.
        """
        resp = utils.mm_exec_wait(
            mm=self.mm,
            vm=vm,
            cmd=cmd,
            timeout=timeout,
            poll_rate=poll_rate,
            debug=debug,
        )

        if resp["exitcode"] != 0:
            raise RuntimeError(
                f"failed to run '{cmd}'\nexitcode: {resp['exitcode']}\nstdout: {resp['stdout']}\nstderr: {resp['stderr']}"
            )

        return resp

    def check_process_running(
        self, vm: str, process: str, os_type: str = "linux"
    ) -> bool:
        if os_type == "linux":
            # "ps -e" cuts off full command name, need "f" to get full command
            ps_list = self.run_and_check_command(
                vm, "ps -ef", timeout=15.0, poll_rate=0.5
            )["stdout"]
        elif os_type == "windows":
            ps_list = self.run_and_check_command(
                vm, "tasklist", timeout=15.0, poll_rate=0.5
            )["stdout"]
        else:
            raise ValueError(f"unknown os_type '{os_type}' for VM {vm}")

        if process.lower() in ps_list.lower():
            return True
        logger.info(f"process '{process}' is not running on '{vm}'")
        return False

    def configure(self) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def cleanup(self) -> None:
        pass


class _MirrorAndBuffer:
    """
    Overwrites a stream to mirror output to the original stream and a buffer.

    This allows Scorch to capture everything written to stdout/stderr (for the
    JSON status file) while ensuring it still reaches the actual stdout/stderr
    streams so it can be picked up by the Phenix logging system.
    """

    def __init__(self, orig_stream, buffer):
        self.orig_stream = orig_stream
        self.buffer = buffer

    def write(self, s):
        self.orig_stream.write(s)
        self.buffer.write(s)
        self.orig_stream.flush()
        self.buffer.flush()

    def flush(self):
        self.orig_stream.flush()
        self.buffer.flush()

    def getvalue(self):
        return self.buffer.getvalue()
