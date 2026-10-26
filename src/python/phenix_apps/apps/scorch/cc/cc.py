import subprocess
import tempfile
import uuid
from pathlib import Path, PurePath

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import error, utils
from phenix_apps.common.logger import logger
from phenix_apps.common.settings import SCORCH_HOST_VALIDATORS


def _windows_script(cmd: str) -> str:
    """Wrap a command in a PowerShell script whose exit code means what it does
    on Linux.

    `powershell -File` exits 0 even when the script's last native command fails,
    so end the script with that command's exit code. A terminating PowerShell
    error already makes `-File` exit 1.
    """
    return f"$global:LASTEXITCODE = 0\n{cmd}\nexit $LASTEXITCODE\n"


def _check_windows_result(args: str, hostname: str, results: dict) -> None:
    """Judge a Windows command by its exit code, as on Linux.

    Windows commands used to fail on any STDERR output instead. During the
    transition nothing that passed before starts failing: a non-zero exit with no
    STDERR only warns (a later release will fail it), and STDERR with exit 0,
    which used to fail, now passes with a warning.
    """
    code, stderr = results["exitcode"], results["stderr"]

    if code and stderr:
        logger.error(f"command '{args}' returned a non-zero exit code of '{code}'")
        logger.info(f"STDERR Output: {stderr}")
        raise RuntimeError(f"command '{args}' failed on Windows")

    if code:
        logger.warning(
            f"command '{args}' on Windows VM {hostname} exited {code} without "
            "writing to STDERR; it passes for now, but a later release will fail "
            "it, as on Linux"
        )
    elif stderr:
        logger.warning(
            f"command '{args}' on Windows VM {hostname} wrote to STDERR but exited "
            "0; Windows commands no longer fail on STDERR alone"
        )
        logger.info(f"STDERR Output: {stderr}")


class CC(ComponentBase):
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

    def __run(self, stage: str) -> None:
        nodes = self.extract_node_names()
        vms = self.metadata.get("vms", [])
        commands = self.metadata.get(stage, [])

        for cmd in commands:
            if cmd.type == "reset":
                self.__reset_cc()
            elif cmd.type == "exec":
                once = cmd.get("once", True)
                filter_ = cmd.get("filter", None)
                if filter_:
                    self.mm.cc_filter(filter_)

                if once:
                    self.mm.cc_exec_once(cmd.args)
                else:
                    self.mm.cc_exec(cmd.args)

                logger.info(
                    f"command '{cmd.args}' executed with filter '{filter_}' using cc"
                )
            else:
                raise ValueError(
                    f"Unknown command type '{cmd.type}' for stage '{stage}'"
                )

        for vm in vms:
            if vm.hostname not in nodes:
                logger.error(f"{vm.hostname} is not in the topology")
                continue

            commands = vm.get(stage, [])

            if len(commands) == 0:
                logger.info(f"{vm.hostname} has no commands for stage {stage}")
                continue

            for cmd in commands:
                if cmd.type == "exec":
                    validator = cmd.get("validator", None)
                    wait = cmd.get("wait", False)
                    once = cmd.get("once", True)

                    if validator:
                        wait = True  # force waiting so validation can occur

                    logger.info(f"executing command '{cmd.args}' in VM {vm.hostname}")

                    script = self.__send_cmd_as_file(vm.hostname, cmd.args)

                    if wait:
                        results = utils.mm_exec_wait(
                            self.mm, vm.hostname, script, once=once
                        )

                        logger.info(
                            f"command '{cmd.args}' executed in VM {vm.hostname} using cc"
                        )

                        if self.extract_node_os_type(vm.hostname) == "windows":
                            _check_windows_result(cmd.args, vm.hostname, results)
                        elif results["exitcode"]:
                            logger.error(
                                f"command '{cmd.args}' returned a non-zero exit code of '{results['exitcode']}'"
                            )

                            if results["stderr"]:
                                logger.info(f"STDERR Output: {results['stderr']}")

                            raise RuntimeError(f"command '{cmd.args}' failed")

                        if results["stdout"]:
                            logger.info(f"STDOUT Output: {results['stdout']}")

                        if validator and not SCORCH_HOST_VALIDATORS:
                            logger.warning(
                                f"skipping host-side validator for command '{cmd.args}' on VM {vm.hostname}: "
                                "host-side commands are disabled by PHENIX_SCORCH_HOST_VALIDATORS=0"
                            )
                        elif validator:
                            logger.info(f"validating results from '{cmd.args}'")

                            with tempfile.NamedTemporaryFile("w", suffix=".sh") as tf:
                                tf.write(validator)
                                tf.flush()

                                proc = subprocess.run(
                                    ["bash", tf.name, vm.hostname],
                                    input=results["stdout"].encode(),
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
                    else:
                        utils.mm_cc_filter_vm(self.mm, vm.hostname)

                        if once:
                            self.mm.cc_exec_once(script)
                        else:
                            self.mm.cc_exec(script)

                        logger.info(
                            f"command '{cmd.args}' executed in VM {vm.hostname} using cc"
                        )
                elif cmd.type == "background":
                    once = cmd.get("once", True)

                    logger.info(
                        f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc"
                    )

                    script = self.__send_cmd_as_file(vm.hostname, cmd.args)

                    utils.mm_cc_filter_vm(self.mm, vm.hostname)

                    if once:
                        self.mm.cc_background_once(script)
                    else:
                        self.mm.cc_background(script)

                    self.mm.clear_cc_filter()
                    logger.info(
                        f"command '{cmd.args}' backgrounded in VM {vm.hostname}"
                    )
                elif cmd.type == "send":
                    args = cmd.args.split(":")
                    src = None
                    dst = None

                    if len(args) == 1:
                        src = dst = args[0]
                    elif len(args) == 2:
                        src = args[0]
                        dst = args[1]
                    else:
                        raise ValueError(
                            f"too many files provided for send command for VM {vm.hostname}: {cmd.args}"
                        )

                    if not PurePath(src).is_absolute():
                        src = "/phenix/" + src

                    if not PurePath(dst).is_absolute():
                        dst = "/phenix/" + dst

                    logger.info(
                        f"sending file '{src}' to VM {vm.hostname} at '{dst}' using cc"
                    )

                    try:
                        utils.mm_send(self.mm, vm.hostname, src, dst)
                        logger.info(f"file '{src}' sent to VM {vm.hostname} at '{dst}'")
                    except Exception as ex:
                        raise RuntimeError(
                            f"error sending '{src}' to VM {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "recv":
                    args = cmd.args.split(":")
                    src = None
                    dst = None

                    if len(args) == 1:
                        src = args[0]
                        dst = str(self.base_dir / PurePath(src).name)
                    elif len(args) == 2:
                        src = args[0]
                        dst_path = Path(args[1])
                        if dst_path.is_absolute():
                            if not dst_path.is_relative_to(self.base_dir):
                                raise error.AppError(
                                    f"path '{dst_path}' escapes base directory '{self.base_dir}'"
                                )
                            dst_path = dst_path.relative_to(self.base_dir)
                        dst = str(utils.safe_join(self.base_dir, dst_path))
                    else:
                        raise ValueError(
                            f"too many files provided for recv command for VM {vm.hostname}: {cmd.args}"
                        )

                    logger.info(
                        f"receiving file '{src}' from VM {vm.hostname} to `{dst}` using cc"
                    )

                    try:
                        utils.mm_recv(self.mm, vm.hostname, src, dst)
                        logger.info(
                            f"file '{src}' received from VM {vm.hostname} to `{dst}`"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"error receiving '{src}' from VM {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "reset":
                    self.__reset_cc()
                else:
                    raise ValueError(
                        f"Unknown command type '{cmd.type}' for VM '{vm.hostname}' and stage '{stage}'"
                    )

    def __send_cmd_as_file(self, hostname, cmd):
        cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}"
        windows = self.extract_node_os_type(hostname) == "windows"
        cmd_file += ".ps1" if windows else ".sh"

        cmd_src = str(Path(self.root_dir) / self.exp_name / cmd_file)
        cmd_dst = str(PurePath("/tmp/miniccc/files") / self.exp_name / cmd_file)

        with Path(cmd_src).open("w") as f:
            f.write(_windows_script(cmd) if windows else cmd)

        utils.mm_cc_send_wait(self.mm, hostname, cmd_src, self.exp_name)
        self.mm.clear_cc_filter()

        Path(cmd_src).unlink()

        if windows:
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
