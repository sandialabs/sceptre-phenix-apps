import json
import os
import time
import uuid

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

PHENIX_PLANNER_ID = "d3810025-f28d-49a0-9021-73e9dac8e8e4"


class Caldera(ComponentBase):
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

    def __run(self, stage):
        server = self.metadata.get("server")
        adversary = self.metadata.get("adversary")
        facts = self.metadata.get("facts")
        planner = self.metadata.get("planner", PHENIX_PLANNER_ID)

        if not server:
            raise ValueError(f"no server provided for '{self.name}' operation")

        if not adversary:
            raise ValueError(f"no adversary provided for '{self.name}' operation")

        if not facts:
            raise ValueError(f"no facts provided for '{self.name}' operation")

        if planner == PHENIX_PLANNER_ID:
            msg = f"Running Caldera operation in stage {stage} with '{adversary}' adversary using '{facts}' fact source and default 'phenix' planner."
        else:
            msg = f"Running Caldera operation in stage {stage} with '{adversary}' adversary using '{facts}' fact source and '{planner}' planner."

        logger.info(msg)

        templates = utils.abs_path(__file__, "templates/")

        op = {"name": self.name}
        mm = self.mm_init()

        try:
            uuid.UUID(adversary)
            op["adversary"] = adversary

            logger.info("adversary provided as UUID - not verifying existence")
        except ValueError:
            logger.info(f"looking up ID for '{adversary}' adversary...")

            cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
            cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
            cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

            with open(cmd_src, "w") as f:
                utils.mako_serve_template(
                    "api_call.mako", templates, f, model="adversaries"
                )

            mm.cc_filter(f"name={server}")
            mm.cc_send(cmd_src)

            # wait for file to be sent via cc
            last_cmd = utils.mm_last_command(mm)
            utils.mm_wait_for_cmd(mm, last_cmd["id"])

            os.remove(cmd_src)

            result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

            if result["exitcode"]:
                raise RuntimeError("failed to make API call for adversaries") from None
            adversaries = json.loads(result["stdout"])
            found = False

            for a in adversaries:
                if a["name"] == adversary:
                    logger.info(f"Adversary {adversary}: {a['adversary_id']}")
                    op["adversary"] = a["adversary_id"]
                    found = True

            if not found:
                raise ValueError(f"unable to find '{adversary}' adversary") from None

        try:
            uuid.UUID(facts)
            op["facts"] = facts

            logger.info("fact source provided as UUID - not verifying existence")
        except ValueError:
            logger.info(f"looking up ID for '{facts}' fact source...")

            cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
            cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
            cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

            with open(cmd_src, "w") as f:
                utils.mako_serve_template(
                    "api_call.mako", templates, f, model="sources"
                )

            mm.cc_filter(f"name={server}")
            mm.cc_send(cmd_src)

            # wait for file to be sent via cc
            last_cmd = utils.mm_last_command(mm)
            utils.mm_wait_for_cmd(mm, last_cmd["id"])

            os.remove(cmd_src)

            result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

            if result["exitcode"]:
                raise RuntimeError("failed to make API call for sources") from None
            sources = json.loads(result["stdout"])
            found = False

            for s in sources:
                if s["name"] == facts:
                    logger.info(f"Sources {facts}: {s['id']}")
                    op["facts"] = s["id"]
                    found = True

            if not found:
                raise ValueError(f"unable to find '{facts}' sources") from None

        try:
            uuid.UUID(planner)
            op["planner"] = planner

            logger.info("planner provided as UUID - not verifying existence")
        except ValueError:
            logger.info(f"looking up ID for '{planner}' planner...")

            cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
            cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
            cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

            with open(cmd_src, "w") as f:
                utils.mako_serve_template(
                    "api_call.mako", templates, f, model="planners"
                )

            mm.cc_filter(f"name={server}")
            mm.cc_send(cmd_src)

            # wait for file to be sent via cc
            last_cmd = utils.mm_last_command(mm)
            utils.mm_wait_for_cmd(mm, last_cmd["id"])

            os.remove(cmd_src)

            result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

            if result["exitcode"]:
                raise RuntimeError("failed to make API call for planners") from None
            planners = json.loads(result["stdout"])
            found = False

            for p in planners:
                if p["name"] == planner:
                    logger.info(f"Planner {planner}: {p['id']}")
                    op["planner"] = p["id"]
                    found = True

            if not found:
                raise ValueError(f"unable to find '{planner}' planner") from None

        logger.info(
            f"creating and starting new operation named '{self.name} in Caldera..."
        )

        cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
        cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
        cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

        with open(cmd_src, "w") as f:
            utils.mako_serve_template("new_operation.mako", templates, f, op=op)

        mm.cc_filter(f"name={server}")
        mm.cc_send(cmd_src)

        # wait for file to be sent via cc
        last_cmd = utils.mm_last_command(mm)
        utils.mm_wait_for_cmd(mm, last_cmd["id"])

        os.remove(cmd_src)

        result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

        if result["exitcode"]:
            raise RuntimeError("failed to make API call for new operation")
        operation = json.loads(result["stdout"])
        op["id"] = operation["id"]

        while True:
            time.sleep(10)

            cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
            cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
            cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

            with open(cmd_src, "w") as f:
                utils.mako_serve_template(
                    "get_operation.mako", templates, f, op=op["id"]
                )

            mm.cc_filter(f"name={server}")
            mm.cc_send(cmd_src)

            # wait for file to be sent via cc
            last_cmd = utils.mm_last_command(mm)
            utils.mm_wait_for_cmd(mm, last_cmd["id"])

            os.remove(cmd_src)

            result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

            if result["exitcode"]:
                raise RuntimeError("failed to make API call for existing operation")
            operation = json.loads(result["stdout"])

            if operation["state"] == "finished":
                logger.info(f"operation {self.name} has finished")
                break
            logger.info(f"operation {self.name} is still running...")

        logger.info(f"exporting Caldera report for '{self.name}' operation...")

        cmd_file = f"run-{self.extract_run_name()}_{uuid.uuid4()!s}.sh"
        cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
        cmd_dst = os.path.join("/tmp/miniccc/files", self.exp_name, cmd_file)

        with open(cmd_src, "w") as f:
            utils.mako_serve_template(
                "get_operation_report.mako", templates, f, op=op["id"]
            )

        mm.cc_filter(f"name={server}")
        mm.cc_send(cmd_src)

        # wait for file to be sent via cc
        last_cmd = utils.mm_last_command(mm)
        utils.mm_wait_for_cmd(mm, last_cmd["id"])

        os.remove(cmd_src)

        result = utils.mm_exec_wait(mm, server, f"bash {cmd_dst}", once=True)

        if result["exitcode"]:
            raise RuntimeError("failed to make API call for operation report")
        report = json.loads(result["stdout"])

        output_file = os.path.join(self.base_dir, "caldera-report.json")
        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)


def main():
    Caldera()


if __name__ == "__main__":
    main()
