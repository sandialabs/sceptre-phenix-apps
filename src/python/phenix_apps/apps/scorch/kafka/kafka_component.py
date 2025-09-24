import json
import os
import shlex
import subprocess
from pathlib import Path

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger


class Kafka(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "kafka")
        self.pid_file = (
            f"/tmp/phenix-scorch-kafka-{self.exp_name}.pid"
        )
        self.started = False
        self.configured = False
        self.execute_stage()

    # configure just calls start
    def configure(self):
        # if we call the start and configure changes, only run the
        # component once
        if self.started:
            return
        else:
            self.start()
            self.configured = True

    def start(self):
        # if we've already configured the element, return
        if self.configured:
            return
        self.started = True
        logger.log("INFO", f"Starting user component: {self.name}")

        # get kafka ip addresses and concatenate them into a list of
        # strings in format ip:port
        kafka_ips = []
        kafka_endpoints = self.metadata.get(
            "kafka_endpoints", [{"ip": "127.0.0.1", "port": "9092"}]
        )
        wait_duration_seconds = self.metadata.get("wait_duration_seconds", 305)

        for item in kafka_endpoints:
            kafka_ips.append(item["ip"] + ":" + item["port"])

        logger.log("INFO", f"Kafka_ips list: {kafka_ips}")

        topics = self.metadata.get("topics", [])
        csv_bool = self.metadata.get(
            "csv", True
        )  # if false output a JSON

        # get and output the output directory to the logger
        output_dir = self.base_dir
        logger.log("INFO", f"Output Directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)
        if csv_bool:
            self.path = os.path.join(
                output_dir, f"{self.name}_output.csv"
            )
        else:
            self.path = os.path.join(
                output_dir, f"{self.name}_output.ndjson"
            )

        kafka_ips_str = ",".join(kafka_ips)
        topics_str = json.dumps(topics)

        print(f"Output Directory: {output_dir}")

        # pass the inputs to the python file (which we execute as a
        # separate process)
        executable = str(
            Path(Path(__file__).parent, "kafka_listener.py")
        )
        arguments = (
            f"python3 {executable} {csv_bool} '{self.path}' "
            f"{kafka_ips_str} '{topics_str}' "
            f"'{self.exp_name}' '{wait_duration_seconds}'"
        )
        command = shlex.split(arguments)

        try:
            response = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            # write PID to a file so that it can be found
            # and killed later
            self._create_pid_file(
                response.pid
            )

            # prevents hang
            response.poll()
        except Exception as e:
            self.eprint(
                f"Error running listener executable. See: {e}"
            )

    def _create_pid_file(self, pid):
        # writes PID to unique .pid file under /tmp directory
        try:
            with open(self.pid_file, "w+") as f:
                f.write(str(pid))
        except Exception as e:
            self.eprint(
                f"Could not create PID file. Listener process at PID {pid} "
                f"will not terminate automatically when experiment ends. "
                f"See: {e}"
            )

    def _consume_pid_file(self):
        # reads and deletes PID file, returns PID
        pid = 0
        try:
            with open(self.pid_file) as f:
                pid = int(f.readline().rstrip())
            os.remove(self.pid_file)
            return pid
        except Exception as e:
            self.eprint(
                f"Error consuming PID file."
                f"Listener process at PID {pid} "
                f"will not be terminated. See: {e}"
            )
            return pid

    def stop(self):
        # stops listener executable
        pid = self._consume_pid_file()

        if not pid:
            logger.log("INFO", f"Stopped user component: {self.name}")
            exit()

        try:
            os.kill(pid, 9)
            logger.log("INFO", f"Stopped user component: {self.name}")
        except Exception as e:
            self.eprint(
                f"Error terminating listener at PID {pid}. See: {e}"
            )

    # cleanup is the same as stop
    def cleanup(self):
        self.stop()


def main():
    Kafka()


if __name__ == "__main__":
    main()
