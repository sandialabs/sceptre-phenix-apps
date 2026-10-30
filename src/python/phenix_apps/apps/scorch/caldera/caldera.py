import json
import time
import uuid
from pathlib import PurePath
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Hostname, Seconds
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

PHENIX_PLANNER_ID: Final[str] = "d3810025-f28d-49a0-9021-73e9dac8e8e4"

# A Caldera object name or UUID. The mako templates JSON-encode it; the body is
# then wrapped in a single-quoted shell string, so only control characters and
# "'" are rejected.
CalderaRef = Annotated[str, Field(pattern=r"^[^\x00-\x1f\x7f']+$")]


class CalderaMetadata(BaseModel):
    """Metadata for the caldera component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    server: Hostname
    adversary: CalderaRef
    facts: CalderaRef
    planner: CalderaRef = PHENIX_PLANNER_ID
    # how often to poll Caldera for the operation's state while it runs
    poll_seconds: Seconds = 10.0


class Caldera(ComponentBase):
    metadata_model = CalderaMetadata
    config: CalderaMetadata

    def __init__(self):
        ComponentBase.__init__(self, "caldera")

        self.execute_stage()

    def configure(self):
        self.__run("configure")

    def start(self):
        self.__run("start")

    def stop(self):
        self.__run("stop")

    def cleanup(self):
        self.__run("cleanup")

    def _api(self, template, what, **kwargs):
        """Render a template to a script, run it on the server VM, return its JSON."""
        templates = utils.abs_path(__file__, "templates/")

        cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
        cmd_src = self.root_dir / self.exp_name / cmd_file
        cmd_dst = PurePath("/tmp/miniccc/files") / self.exp_name / cmd_file

        with cmd_src.open("w") as f:
            utils.mako_serve_template(template, templates, f, **kwargs)

        utils.mm_cc_send_wait(self.mm, self.config.server, str(cmd_src), self.exp_name)

        cmd_src.unlink()

        result = utils.mm_exec_wait(
            self.mm, self.config.server, f"bash {cmd_dst}", once=True
        )

        if result["exitcode"]:
            raise RuntimeError(f"failed to make API call for {what}")
        return json.loads(result["stdout"])

    def _resolve(self, model, kind, ref):
        """Return the Caldera ID for a name; UUIDs are used as-is."""
        try:
            uuid.UUID(ref)
            logger.info(f"{kind} provided as UUID - not verifying existence")
            return ref
        except ValueError:
            pass

        logger.info(f"looking up ID for '{ref}' {kind}...")

        for item in self._api("api_call.mako", model, model=model):
            if item["name"] == ref:
                id_ = item.get("adversary_id") or item["id"]
                logger.info(f"{kind} {ref}: {id_}")
                return id_

        raise ValueError(f"unable to find '{ref}' {kind}")

    def __run(self, stage):
        adversary = self.config.adversary
        facts = self.config.facts
        planner = self.config.planner

        if planner == PHENIX_PLANNER_ID:
            msg = f"Running Caldera operation in stage {stage} with '{adversary}' adversary using '{facts}' fact source and default 'phenix' planner."
        else:
            msg = f"Running Caldera operation in stage {stage} with '{adversary}' adversary using '{facts}' fact source and '{planner}' planner."

        logger.info(msg)

        op = {"name": self.name}

        op["adversary"] = self._resolve("adversaries", "adversary", adversary)
        op["facts"] = self._resolve("sources", "fact source", facts)
        op["planner"] = self._resolve("planners", "planner", planner)

        logger.info(
            f"creating and starting new operation named '{self.name} in Caldera..."
        )

        operation = self._api("new_operation.mako", "new operation", op=op)
        op["id"] = operation["id"]

        while True:
            time.sleep(self.config.poll_seconds)

            operation = self._api(
                "get_operation.mako", "existing operation", op=op["id"]
            )

            if operation["state"] == "finished":
                logger.info(f"operation {self.name} has finished")
                break
            logger.info(f"operation {self.name} is still running...")

        logger.info(f"exporting Caldera report for '{self.name}' operation...")

        report = self._api("get_operation_report.mako", "operation report", op=op["id"])

        output_file = self.base_dir / "caldera-report.json"
        with output_file.open("w") as f:
            json.dump(report, f, indent=2)


def main():
    Caldera()


if __name__ == "__main__":
    main()
