import os
import subprocess
import uuid

from box import Box

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class AtomicRedTeam(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "art")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        goart = self.metadata.get("framework", None)
        technique = self.metadata.get("technique", None)
        test_name = self.metadata.get("testName", None)
        test_index = self.metadata.get("testIndex", None)

        mm = self.mm_init()

        if not goart or not os.path.exists(goart):
            raise RuntimeError("goart executable not found")

        if not technique:
            raise ValueError("no technique configured")

        if test_name is None and test_index is None:
            raise ValueError("no technique test configured")

        vms = self.metadata.get("vms", None)

        for vm in vms:
            logger.info(f"copying {goart} to {vm.hostname}")

            utils.mm_send(mm, vm.hostname, goart, f"/tmp/{os.path.basename(goart)}")

            mm.cc_filter(f"name={vm.hostname}")
            mm.cc_exec(f"chmod +x /tmp/{os.path.basename(goart)}")

            args = ["-q", "-f", "json", "-t", self.metadata.technique]

            out_file = f"/tmp/{uuid.uuid4()!s}.json"

            args.extend(["-o", out_file])

            if test_index is not None:
                args.extend(["-i", str(test_index)])
            elif test_name is not None:
                args.extend(["-n", test_name])
            else:  # should never get here...
                raise ValueError("no technique test configured")

            inputs = vm.get("inputs", {})
            for name, value in inputs.items():
                args.extend(["--input", f"{name}={value}"])

            env = self.metadata.get("env", {})
            for name, value in env.items():
                args.extend(["--env", f"{name}={value}"])

            env = vm.get("env", {})
            for name, value in env.items():
                args.extend(["--env", f"{name}={value}"])

            cmd = f"/tmp/{os.path.basename(goart)} {' '.join(args)}"

            logger.info(f"executing {cmd} in {vm.hostname}")

            utils.mm_exec_wait(mm, vm.hostname, cmd)

            logger.info(f"getting results file {out_file} from {vm.hostname}")

            results_file = os.path.join(self.base_dir, f"{vm.hostname}.json")

            try:
                utils.mm_recv(mm, vm.hostname, out_file, results_file)
            except Exception as ex:
                raise RuntimeError(f"failed to get results file: {ex}") from ex

            validator = self.metadata.get("validator", None)

            if validator:
                logger.info(f"validating results from {vm.hostname}")

                tempfile = f"/tmp/{uuid.uuid4()!s}.sh"

                with open(tempfile, "w") as tf:
                    tf.write(validator)

                results = Box.from_json(filename=results_file)

                proc = subprocess.run(
                    ["sh", tempfile, vm.hostname],
                    input=results.Executor.ExecutedCommand.results.encode(),
                    capture_output=True,
                )

                if proc.returncode != 0:
                    stderr = proc.stderr.decode()
                    if stderr:
                        logger.error(f"results validation failed: {stderr}")
                    else:
                        logger.error("results validation failed")

                    if self.metadata.get("abortOnError", False):
                        raise RuntimeError("results validation failed")
                else:
                    logger.info("results are valid")

                os.remove(tempfile)

        logger.info(f"Started user component: {self.name}")


def main():
    AtomicRedTeam()


if __name__ == "__main__":
    main()
