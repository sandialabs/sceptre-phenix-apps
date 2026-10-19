import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Final

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger

LISTENER: Final[Path] = Path(__file__).with_name("kafka_listener.py")


class Kafka(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "kafka")

        # generate a universal uid so that multiple kafka components can run simultaneously
        config_str = json.dumps(self.metadata, sort_keys=True)
        component_uuid = uuid.uuid5(
            uuid.NAMESPACE_DNS, f"{self.exp_name}-{self.name}-{config_str}"
        )

        # Not under base_dir: that is per loop and count, and configure must see
        # the PID file a previous loop wrote. Not /tmp, which is world-writable.
        self.component_id = component_uuid.hex
        self.pid_file = (
            Path(self.files_dir)
            / "scorch"
            / f"phenix-scorch-kafka-{self.exp_name}-{self.component_id}.pid"
        )
        self.execute_stage()

    def configure(self):
        # if the deterministic PID file names a running listener, don't configure
        # the component again; a stale file (crash, reboot) is discarded
        if self.pid_file.exists():
            try:
                pid = int(self.pid_file.read_text().strip())
            except (OSError, ValueError):
                pid = 0
            if pid and self._is_listener(pid):
                logger.info(f"User component {self.name} already configured, skipping")
                return
            logger.warning(f"Removing stale PID file {self.pid_file}")
            self.pid_file.unlink(missing_ok=True)

        logger.info(f"Configuring user component: {self.name}")

        # get kafka ip addresses and concatenate them into a list of
        # strings in format ip:port
        kafka_ips = []
        kafka_endpoints = self.metadata.get(
            "kafka_endpoints", [{"ip": "127.0.0.1", "port": "9092"}]
        )
        wait_duration_seconds = self.metadata.get("wait_duration_seconds", 305)

        for item in kafka_endpoints:
            kafka_ips.append(item["ip"] + ":" + item["port"])

        logger.info(f"Kafka_ips list: {kafka_ips}")

        topics = self.metadata.get("topics", [])
        csv_bool = self.metadata.get("csv", True)  # if false output a JSON

        # get and output the output directory to the logger
        output_dir: Path = self.base_dir
        logger.info(f"Output Directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        if csv_bool:
            self.path = output_dir / f"{self.name}_output.csv"
        else:
            self.path = output_dir / f"{self.name}_output.ndjson"

        kafka_ips_str = ",".join(kafka_ips)
        topics_str = json.dumps(topics)

        # pass the inputs to the python file (which we execute as a
        # separate process)
        arguments = (
            f"python3 {LISTENER} {csv_bool} '{self.path}' "
            f"{kafka_ips_str} '{topics_str}' "
            f"'{self.exp_name}' '{wait_duration_seconds}' {self.component_id}"
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
            self._create_pid_file(response.pid)

            # prevents hang
            response.poll()
        except Exception as e:
            logger.error(f"Error running listener executable. See: {e}")

    def _create_pid_file(self, pid):
        # writes PID to the unique .pid file
        try:
            with self.pid_file.open("w+") as f:
                f.write(str(pid))
        except Exception as e:
            logger.error(
                f"Could not create PID file. Listener process at PID {pid} "
                f"will not terminate automatically when experiment ends. "
                f"See: {e}"
            )

    def _consume_pid_file(self):
        # reads and deletes PID file, returns PID
        pid = 0
        try:
            with self.pid_file.open() as f:
                pid = int(f.readline().rstrip())
            self.pid_file.unlink()
            return pid
        except Exception as e:
            logger.error(
                f"Error consuming PID file.Listener process at PID {pid} will not be terminated. See: {e}"
            )
            return pid

    def cleanup(self):
        # stops listener executable
        pid = self._consume_pid_file()

        if not pid:
            logger.info("No PID, component already cleaned up")
            exit()

        if not self._is_listener(pid):
            logger.error(
                f"PID {pid} does not appear to be a kafka listener process, not killing"
            )
            return

        try:
            os.kill(pid, 9)
            logger.info(f"Cleaned up user component: {self.name}")
        except Exception as e:
            logger.error(f"Error terminating listener at PID {pid}. See: {e}")

    def _is_listener(self, pid: int) -> bool:
        # Match whole argv entries: the script, the experiment, and this
        # component's id (a trailing argv entry the listener ignores), so an
        # editor, another experiment's listener or a sibling kafka component
        # that reused the PID is not mistaken for ours.
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            return False
        return all(
            want.encode() in argv
            for want in (str(LISTENER), self.exp_name, self.component_id)
        )


def main():
    Kafka()


if __name__ == "__main__":
    main()
