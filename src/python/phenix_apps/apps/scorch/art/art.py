import os
import subprocess
import uuid

from box import Box

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

GOART_BASE = "/phenix/art"


class AtomicRedTeam(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "art")
        self.execute_stage()

    def _get_os_type(self, hostname):
        node = self.extract_node(hostname)
        return node.get("hardware", {}).get("os_type", "linux").lower()

    def _goart_path(self, os_type):
        if os_type == "windows":
            return "C:/phenix/art/goart.exe"
        return f"{GOART_BASE}/goart"

    def _tmp_path(self, os_type, filename):
        if os_type == "windows":
            return f"C:/Windows/Temp/{filename}"
        return f"/tmp/{filename}"

    def _check_binary(self, mm, hostname, goart_path, os_type):
        if os_type == "windows":
            shell_cmd = f'cmd /c "if not exist {goart_path} exit 1"'
        else:
            shell_cmd = f"test -x {goart_path}"

        try:
            utils.mm_exec_wait(mm, hostname, shell_cmd)
        except Exception:
            raise RuntimeError(
                f"goart not found or not executable at {goart_path} on {hostname}. "
                f"Ensure it is injected via topology."
            )

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        technique = self.metadata.get("technique", None)
        test_name = self.metadata.get("testName", None)
        test_index = self.metadata.get("testIndex", None)
        abort_on_error = self.metadata.get("abortOnError", False)

        if not technique:
            raise ValueError("no technique configured")

        if test_name is None and test_index is None:
            raise ValueError("no technique test configured (set testName or testIndex)")

        vms = self.metadata.get("vms", None)
        if not vms:
            raise ValueError("no vms configured")

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.hostname
            os_type = self._get_os_type(hostname)
            goart_path = self._goart_path(os_type)
            out_filename = f"{uuid.uuid4()!s}.json"
            out_file = self._tmp_path(os_type, out_filename)

            logger.info(f"targeting {hostname} (os_type={os_type})")
            logger.info(f"goart path: {goart_path}")
            logger.info(f"output file: {out_file}")
            logger.info(f"base_dir: {self.base_dir}")

            self._check_binary(mm, hostname, goart_path, os_type)

            args = ["-q", "-f", "json", "-t", technique, "-o", out_file]

            if test_index is not None:
                args.extend(["-i", str(test_index)])
            elif test_name is not None:
                args.extend(["-n", test_name])

            for name, value in self.metadata.get("env", {}).items():
                args.extend(["--env", f"{name}={value}"])

            for name, value in vm.get("env", {}).items():
                args.extend(["--env", f"{name}={value}"])

            for name, value in vm.get("inputs", {}).items():
                args.extend(["--input", f"{name}={value}"])

            cmd = f"{goart_path} {' '.join(args)}"

            logger.info(f"executing: {cmd}")
            utils.mm_exec_wait(mm, hostname, cmd)

            logger.info(f"retrieving results: {out_file}")
            results_file = os.path.join(self.base_dir, f"{hostname}.json")

            try:
                utils.mm_recv(mm, hostname, out_file, results_file)
                logger.info(f"results_file path: {results_file}")
                logger.info(f"results_file exists: {os.path.exists(results_file)}")
            except Exception as ex:
                raise RuntimeError(f"failed to get results file from {hostname}: {ex}") from ex

            validator = self.metadata.get("validator", None)
            if validator:
                logger.info(f"validating results from {hostname}")

                tempfile = f"/tmp/{uuid.uuid4()!s}.sh"
                with open(tempfile, "w") as tf:
                    tf.write(validator)

                results = Box.from_json(filename=results_file)

                proc = subprocess.run(
                    ["sh", tempfile, hostname],
                    input=results.Executor.ExecutedCommand.results.encode(),
                    capture_output=True,
                )

                os.remove(tempfile)

                if proc.returncode != 0:
                    stderr = proc.stderr.decode()
                    logger.error(f"results validation failed: {stderr}" if stderr else "results validation failed")
                    if abort_on_error:
                        raise RuntimeError("results validation failed")
                else:
                    logger.info("results are valid")

        logger.info(f"Started user component: {self.name}")


def main():
    AtomicRedTeam()


if __name__ == "__main__":
    main()