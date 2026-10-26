import shlex
import subprocess
import tempfile
import time
import uuid
from typing import Annotated, Final, Self

from box import Box
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    MetadataBlock,
    Name,
    Seconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger
from phenix_apps.common.settings import SCORCH_HOST_VALIDATORS

# This can be changed here to reflect your directory structure on hosts as a default.
# This is overwritten if a value is provided via goartPath
GOART_BASE: Final[str] = "/phenix/art"

# env/input names and values land on the goart command line unquoted, so no
# whitespace, quotes or shell operators
EnvKey = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]
EnvValue = Annotated[str, Field(pattern=r"^[^\s'\"`$;&|<>\\]*$")]
# atomic test names have spaces ("Dump LSASS memory"), so unlike a Token this
# allows them
TestName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_ .,:=@%/+()-]*$")]


class VM(MetadataBlock):
    hostname: Hostname
    env: dict[EnvKey, EnvValue] = Field(default_factory=dict)
    inputs: dict[EnvKey, EnvValue] = Field(default_factory=dict)


class ARTMetadata(BaseModel):
    """Metadata for the art component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    technique: Name
    testName: TestName | None = None
    testIndex: NonNegativeInt | None = None
    abortOnError: bool = False
    goartPath: FilePath | None = None
    env: dict[EnvKey, EnvValue] = Field(default_factory=dict)
    # pause after running the test so goart finishes writing the output file
    # before it is retrieved off the VM
    settleSeconds: Seconds = 5.0
    validator: str | None = None
    vms: Annotated[list[VM], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_test(self) -> Self:
        if self.testName is None and self.testIndex is None:
            raise ValueError("no technique test configured (set testName or testIndex)")
        return self


class AtomicRedTeam(ComponentBase):
    metadata_model = ARTMetadata
    config: ARTMetadata

    def __init__(self):
        ComponentBase.__init__(self, "art")
        self.execute_stage()

    def _goart_path(self, os_type):
        if self.config.goartPath:
            return self.config.goartPath
        if os_type == "windows":
            return "C:/phenix/art/goart.exe"
        return f"{GOART_BASE}/goart"

    def _tmp_path(self, os_type, filename):
        if os_type == "windows":
            return f"/phenix/art/{filename}"
        return f"/tmp/{filename}"

    def _check_binary(self, hostname, goart_path, os_type):
        if os_type == "windows":
            shell_cmd = f'cmd /c "if not exist {goart_path} exit 1"'
        else:
            shell_cmd = f"test -x {goart_path}"
        try:
            utils.mm_exec_wait(self.mm, hostname, shell_cmd)
        except Exception as ex:
            raise RuntimeError(
                f"goart not found or not executable at {goart_path} on {hostname}. "
                f"Ensure it is injected via topology."
            ) from ex

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        for vm in self.config.vms:
            hostname = vm.hostname
            os_type = self.extract_node_os_type(hostname)
            goart_path = self._goart_path(os_type)
            out_filename = f"{uuid.uuid4()!s}.json"
            out_file = self._tmp_path(os_type, out_filename)

            logger.info(
                f"targeting {hostname} (os_type={os_type}), goart path "
                f"{goart_path}, output file {out_file}, base_dir {self.base_dir}"
            )

            self._check_binary(hostname, goart_path, os_type)

            args = [
                "-q",
                "-f",
                "json",
                "-t",
                shlex.quote(self.config.technique),
                "-o",
                out_file,
            ]

            if self.config.testIndex is not None:
                args.extend(["-i", str(self.config.testIndex)])
            elif self.config.testName is not None:
                args.extend(["-n", shlex.quote(self.config.testName)])

            for name, value in self.config.env.items():
                args.extend(["--env", shlex.quote(f"{name}={value}")])

            for name, value in vm.env.items():
                args.extend(["--env", shlex.quote(f"{name}={value}")])

            for name, value in vm.inputs.items():
                args.extend(["--input", shlex.quote(f"{name}={value}")])

            cmd = f"{goart_path} {' '.join(args)}"

            logger.info(f"executing: {cmd}")
            utils.mm_exec_wait(self.mm, hostname, cmd)
            time.sleep(self.config.settleSeconds)
            logger.info(f"retrieving results: {out_file}")
            results_file = self.base_dir / f"{hostname}.json"

            try:
                utils.mm_recv(self.mm, hostname, out_file, results_file)
                if not results_file.is_file():
                    raise FileNotFoundError(f"{results_file} not found after transfer")
                logger.info(f"results_file path: {results_file}")
            except Exception as ex:
                raise RuntimeError(
                    f"failed to get results file from {hostname}: {ex}"
                ) from ex

            validator = self.config.validator
            if validator and not SCORCH_HOST_VALIDATORS:
                logger.warning(
                    f"skipping host-side validator for {hostname}: "
                    "host-side commands are disabled by PHENIX_SCORCH_HOST_VALIDATORS=0"
                )
            elif validator:
                logger.info(f"validating results from {hostname}")

                results = Box.from_json(filename=results_file)

                with tempfile.NamedTemporaryFile("w", suffix=".sh") as tf:
                    tf.write(validator)
                    tf.flush()

                    proc = subprocess.run(
                        ["sh", tf.name, hostname],
                        input=results.Executor.ExecutedCommand.results.encode(),
                        capture_output=True,
                    )

                if proc.returncode != 0:
                    stderr = proc.stderr.decode()
                    logger.error(
                        f"results validation failed: {stderr}"
                        if stderr
                        else "results validation failed"
                    )
                    if self.config.abortOnError:
                        raise RuntimeError("results validation failed")
                else:
                    logger.info("results are valid")

        logger.info(f"Started user component: {self.name}")


def main():
    AtomicRedTeam()


if __name__ == "__main__":
    main()
