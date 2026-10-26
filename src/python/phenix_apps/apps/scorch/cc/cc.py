import subprocess
import tempfile
import uuid
from pathlib import Path, PurePath
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Hostname, MetadataBlock
from phenix_apps.common import error, utils
from phenix_apps.common.logger import logger
from phenix_apps.common.settings import SCORCH_HOST_VALIDATORS

# A stage-level `exec` hands `args` and `filter` to minimega's command lexer
# verbatim (see README, "Notes on Stage-Level args and filter"), so they are
# left almost unconstrained; only newlines and NUL, which would break the
# command on the wire, are refused.
MinimegaRaw = Annotated[str, StringConstraints(min_length=1, pattern=r"^[^\x00\r\n]*$")]

# VM-level `exec` and `background` write `args` to a script file on the VM, so
# the shell on the VM reads them, not minimega: any non-empty text is fine.
ScriptArgs = Annotated[str, StringConstraints(min_length=1)]


def _at_most_one_colon(value: str) -> str:
    # send/recv args are "src" or "src:dst"; a second colon is ambiguous.
    if value.count(":") > 1:
        raise ValueError("expected 'src' or 'src:dst' (at most one ':')")
    return value


# A send/recv file argument: a source path, optionally ':' and a destination.
FileArg = Annotated[
    str, StringConstraints(min_length=1), AfterValidator(_at_most_one_colon)
]


# Each command type gets its own model holding only the fields it uses. The two
# vocabularies are distinct: a stage-level command runs against a cc filter, a
# VM-level command runs against one VM.


class StageReset(MetadataBlock):
    type: Literal["reset"]


class StageExec(MetadataBlock):
    type: Literal["exec"]
    args: MinimegaRaw
    filter: MinimegaRaw | None = None
    once: bool = True

    @field_validator("filter", mode="before")
    @classmethod
    def _empty_filter_is_none(cls, value: Any) -> Any:
        # the old code did `if filter_:`, so `filter: ""` meant "no filter"
        return None if value == "" else value


StageCommand = Annotated[StageReset | StageExec, Field(discriminator="type")]


class VMExec(MetadataBlock):
    type: Literal["exec"]
    args: ScriptArgs
    once: bool = True
    wait: bool = False
    # a bash script run on the phenix host, fed the command's stdout on stdin
    validator: str | None = None

    @model_validator(mode="after")
    def _validator_forces_wait(self) -> "VMExec":
        # a validator can only run on output the component waited for
        if self.validator:
            self.wait = True
        return self


class VMBackground(MetadataBlock):
    type: Literal["background"]
    args: ScriptArgs
    once: bool = True


class VMSend(MetadataBlock):
    type: Literal["send"]
    args: FileArg


class VMRecv(MetadataBlock):
    type: Literal["recv"]
    args: FileArg


class VMReset(MetadataBlock):
    type: Literal["reset"]


VMCommand = Annotated[
    VMExec | VMBackground | VMSend | VMRecv | VMReset,
    Field(discriminator="type"),
]


Stage = Literal["configure", "start", "stop", "cleanup"]
_LIST_KEYS: Final = {"configure", "start", "stop", "cleanup", "vms"}


def _nulls_to_lists(data: Any) -> Any:
    # an empty `start:` in YAML is null; take it as "nothing to do"
    if isinstance(data, dict):
        return {k: [] if v is None and k in _LIST_KEYS else v for k, v in data.items()}
    return data


class VM(MetadataBlock):
    hostname: Hostname
    configure: list[VMCommand] = Field(default_factory=list)
    start: list[VMCommand] = Field(default_factory=list)
    stop: list[VMCommand] = Field(default_factory=list)
    cleanup: list[VMCommand] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _null_lists(cls, data: Any) -> Any:
        return _nulls_to_lists(data)


class CCMetadata(BaseModel):
    """Metadata for the cc component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    configure: list[StageCommand] = Field(default_factory=list)
    start: list[StageCommand] = Field(default_factory=list)
    stop: list[StageCommand] = Field(default_factory=list)
    cleanup: list[StageCommand] = Field(default_factory=list)
    vms: list[VM] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _null_lists(cls, data: Any) -> Any:
        return _nulls_to_lists(data)


class CC(ComponentBase):
    metadata_model = CCMetadata
    config: CCMetadata

    def __init__(self):
        ComponentBase.__init__(self, "cc")

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
        nodes = self.extract_node_names()

        for cmd in getattr(self.config, stage):
            match cmd:
                case StageReset():
                    self.__reset_cc()
                case StageExec():
                    self._stage_exec(cmd)
                case _:
                    raise AssertionError(f"unhandled stage command {cmd!r}")

        for vm in self.config.vms:
            if vm.hostname not in nodes:
                logger.error(f"{vm.hostname} is not in the topology")
                continue

            commands = getattr(vm, stage)

            if len(commands) == 0:
                logger.info(f"{vm.hostname} has no commands for stage {stage}")
                continue

            for cmd in commands:
                match cmd:
                    case VMExec():
                        self._vm_exec(vm, cmd)
                    case VMBackground():
                        self._vm_background(vm, cmd)
                    case VMSend():
                        self._vm_send(vm, cmd)
                    case VMRecv():
                        self._vm_recv(vm, cmd)
                    case VMReset():
                        self.__reset_cc()
                    case _:
                        raise AssertionError(f"unhandled VM command {cmd!r}")

    def _stage_exec(self, cmd: StageExec) -> None:
        if cmd.filter:
            self.mm.cc_filter(cmd.filter)

        if cmd.once:
            self.mm.cc_exec_once(cmd.args)
        else:
            self.mm.cc_exec(cmd.args)

        logger.info(
            f"command '{cmd.args}' executed with filter '{cmd.filter}' using cc"
        )

    def _vm_exec(self, vm: VM, cmd: VMExec) -> None:
        logger.info(f"executing command '{cmd.args}' in VM {vm.hostname}")

        script = self.__send_cmd_as_file(vm.hostname, cmd.args)

        if not cmd.wait:
            utils.mm_cc_filter_vm(self.mm, vm.hostname)

            if cmd.once:
                self.mm.cc_exec_once(script)
            else:
                self.mm.cc_exec(script)

            logger.info(f"command '{cmd.args}' executed in VM {vm.hostname} using cc")
            return

        results = utils.mm_exec_wait(self.mm, vm.hostname, script, once=cmd.once)

        logger.info(f"command '{cmd.args}' executed in VM {vm.hostname} using cc")

        # HACK: If Windows, use presence of stderr to determine
        # success/failure instead of exit code. Ugh...
        if self.extract_node_os_type(vm.hostname) == "windows":
            if results["stderr"]:
                logger.error(
                    f"command '{cmd.args}' resulted in output to STDERR (assuming failure)"
                )
                logger.info(f"STDERR Output: {results['stderr']}")

                raise RuntimeError(f"command '{cmd.args}' failed on Windows")
        elif results["exitcode"]:
            logger.error(
                f"command '{cmd.args}' returned a non-zero exit code of '{results['exitcode']}'"
            )

            if results["stderr"]:
                logger.info(f"STDERR Output: {results['stderr']}")

            raise RuntimeError(f"command '{cmd.args}' failed")

        if results["stdout"]:
            logger.info(f"STDOUT Output: {results['stdout']}")

        if cmd.validator:
            self._validate(vm.hostname, cmd.args, cmd.validator, results["stdout"])

    def _validate(self, hostname: str, args: str, validator: str, stdout: str) -> None:
        if not SCORCH_HOST_VALIDATORS:
            logger.warning(
                f"skipping host-side validator for command '{args}' on VM {hostname}: "
                "host-side commands are disabled by PHENIX_SCORCH_HOST_VALIDATORS=0"
            )
            return

        logger.info(f"validating results from '{args}'")

        with tempfile.NamedTemporaryFile("w", suffix=".sh") as tf:
            tf.write(validator)
            tf.flush()

            proc = subprocess.run(
                ["bash", tf.name, hostname],
                input=stdout.encode(),
                capture_output=True,
            )

        if proc.returncode != 0:
            stderr = proc.stderr.decode()
            if stderr:
                logger.error(f"results validation failed: {stderr}")
            else:
                logger.error("results validation failed")

            raise RuntimeError("results validation failed")
        logger.info("results are valid")

    def _vm_background(self, vm: VM, cmd: VMBackground) -> None:
        logger.info(f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc")

        script = self.__send_cmd_as_file(vm.hostname, cmd.args)

        utils.mm_cc_filter_vm(self.mm, vm.hostname)

        if cmd.once:
            self.mm.cc_background_once(script)
        else:
            self.mm.cc_background(script)

        self.mm.clear_cc_filter()
        logger.info(f"command '{cmd.args}' backgrounded in VM {vm.hostname}")

    def _vm_send(self, vm: VM, cmd: VMSend) -> None:
        parts = cmd.args.split(":")
        if len(parts) == 1:
            src = dst = parts[0]
        else:  # exactly 2; the model rejects a second colon
            src, dst = parts

        if not PurePath(src).is_absolute():
            src = "/phenix/" + src

        if not PurePath(dst).is_absolute():
            dst = "/phenix/" + dst

        logger.info(f"sending file '{src}' to VM {vm.hostname} at '{dst}' using cc")

        try:
            utils.mm_send(self.mm, vm.hostname, src, dst)
            logger.info(f"file '{src}' sent to VM {vm.hostname} at '{dst}'")
        except Exception as ex:
            raise RuntimeError(
                f"error sending '{src}' to VM {vm.hostname}: {ex}"
            ) from ex

    def _vm_recv(self, vm: VM, cmd: VMRecv) -> None:
        parts = cmd.args.split(":")
        if len(parts) == 1:
            src = parts[0]
            dst = str(self.base_dir / PurePath(src).name)
        else:  # exactly 2; the model rejects a second colon
            src = parts[0]
            dst_path = Path(parts[1])
            if dst_path.is_absolute():
                if not dst_path.is_relative_to(self.base_dir):
                    raise error.AppError(
                        f"path '{dst_path}' escapes base directory '{self.base_dir}'"
                    )
                dst_path = dst_path.relative_to(self.base_dir)
            dst = str(utils.safe_join(self.base_dir, dst_path))

        logger.info(f"receiving file '{src}' from VM {vm.hostname} to `{dst}` using cc")

        try:
            utils.mm_recv(self.mm, vm.hostname, src, dst)
            logger.info(f"file '{src}' received from VM {vm.hostname} to `{dst}`")
        except Exception as ex:
            raise RuntimeError(
                f"error receiving '{src}' from VM {vm.hostname}: {ex}"
            ) from ex

    def __send_cmd_as_file(self, hostname, cmd):
        cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}"
        os_type = self.extract_node_os_type(hostname)

        if os_type == "windows":
            cmd_file += ".ps1"
        else:
            cmd_file += ".sh"

        cmd_src = str(Path(self.root_dir) / self.exp_name / cmd_file)
        cmd_dst = str(PurePath("/tmp/miniccc/files") / self.exp_name / cmd_file)

        with Path(cmd_src).open("w") as f:
            f.write(cmd)

        utils.mm_cc_send_wait(self.mm, hostname, cmd_src, self.exp_name)
        self.mm.clear_cc_filter()

        Path(cmd_src).unlink()

        if os_type == "windows":
            return f"powershell.exe -ExecutionPolicy Bypass -File {cmd_dst}"
        return f"bash {cmd_dst}"

    def __reset_cc(self):
        logger.info("deleting miniccc commands and responses")
        self.mm.clear_cc_filter()
        self.mm.cc_delete_command("all")
        self.mm.cc_delete_response("all")
        self.mm.clear_cc_commands()
        self.mm.clear_cc_responses()

        # ensure miniccc_responses directory is empty
        miniccc_dir = utils.mm_get_cc_path(self.mm)
        if miniccc_dir and any(p.exists() for p in miniccc_dir.iterdir()):
            logger.error(
                f"WARNING: miniccc responses still exist in '{miniccc_dir}' even after clearing! number remaining: {len(list(miniccc_dir.iterdir()))}"
            )


def main():
    CC()


if __name__ == "__main__":
    main()
