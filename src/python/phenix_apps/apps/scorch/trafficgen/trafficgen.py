import time
from pathlib import PurePath
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    Interface,
    MetadataBlock,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

Rate = Annotated[int, Field(gt=0, strict=True)]
Probability = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
# whole seconds: the client's --duration is a plain integer
Duration = Annotated[int, Field(ge=0, strict=True)]


class Scripts(MetadataBlock):
    trafficServer: FilePath
    backgroundGen: FilePath | None = None
    malwareGen: FilePath | None = None


class BackgroundClient(MetadataBlock):
    hostname: Hostname = "background-gen"
    rate: Rate = 10000
    probability: Probability = 0.01


class MalwareClient(MetadataBlock):
    hostname: Hostname = "malware-gen"
    rate: Rate = 20
    probability: Probability = 1.25


class Target(MetadataBlock):
    hostname: Hostname = "traffic-server"
    interface: Interface = "IF0"
    duration: Duration = 5
    backgroundClient: BackgroundClient | None = None
    malwareClient: MalwareClient | None = None


class TrafficgenMetadata(BaseModel):
    """Metadata for the trafficgen component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    scripts: Scripts
    targets: Annotated[list[Target], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_scripts(self) -> Self:
        for client, script in (
            ("backgroundClient", "backgroundGen"),
            ("malwareClient", "malwareGen"),
        ):
            if any(getattr(t, client) for t in self.targets) and not getattr(
                self.scripts, script
            ):
                raise ValueError(
                    f"scripts.{script}: required when a target has {client}"
                )
        return self


def _name(script: str | None) -> str:
    # the model validator guarantees the script is set whenever it is used
    return PurePath(script or "").name


class TrafficGen(ComponentBase):
    metadata_model = TrafficgenMetadata
    config: TrafficgenMetadata

    def __init__(self):
        ComponentBase.__init__(self, "trafficgen")

        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        scripts = self.config.scripts

        for target in self.config.targets:
            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/trafficgen-test/scripts/traffic-server.py, then
            # it will be copied to /traffic-server.py in the VM.
            for hostname, script in self._scripts(target, scripts):
                logger.info(f"copying {_name(script)} to {hostname}")

                utils.mm_send(self.mm, hostname, script, _name(script))

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        scripts = self.config.scripts

        for target in self.config.targets:
            target_host = target.hostname
            target_script_name = _name(scripts.trafficServer)
            target_ip = self.extract_node_ip(target_host, target.interface)
            duration = target.duration

            logger.info(f"running {target_script_name} on {target_host}")

            self.mm.cc_filter(f"name={target_host}")
            self.mm.cc_background(f"python3 /{target_script_name}")

            for client, script in (
                (target.backgroundClient, scripts.backgroundGen),
                (target.malwareClient, scripts.malwareGen),
            ):
                if not client:
                    continue

                logger.info(f"running {_name(script)} on {client.hostname}")

                self.mm.cc_filter(f"name={client.hostname}")
                self.mm.cc_background(
                    f"python3 /{_name(script)} --ip {target_ip} "
                    f"--rate {client.rate} --duration {duration} "
                    f"--probability {client.probability}"
                )

            logger.info(
                f"pausing for {duration + 5}s while traffic is generated for {target_host}"
            )

            time.sleep(duration + 5)

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        for target in self.config.targets:
            for hostname, script in self._scripts(target, self.config.scripts):
                logger.info(f"killing {_name(script)} on {hostname}")

                self.mm.cc_filter(f"name={hostname}")
                self.mm.cc_exec(f"pkill -f {_name(script)}")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        for target in self.config.targets:
            for hostname, script in self._scripts(target, self.config.scripts):
                logger.info(f"deleting /{_name(script)} on {hostname}")

                self.mm.cc_filter(f"name={hostname}")
                self.mm.cc_exec(f"rm /{_name(script)}")

        logger.info(f"Cleaned up user component: {self.name}")

    @staticmethod
    def _scripts(target: Target, scripts: Scripts) -> list[tuple[str, str]]:
        """(hostname, script) for the server and each configured client."""

        pairs = [(target.hostname, scripts.trafficServer)]

        for client, script in (
            (target.backgroundClient, scripts.backgroundGen),
            (target.malwareClient, scripts.malwareGen),
        ):
            if client and script:
                pairs.append((client.hostname, script))

        return pairs


def main():
    TrafficGen()


if __name__ == "__main__":
    main()
