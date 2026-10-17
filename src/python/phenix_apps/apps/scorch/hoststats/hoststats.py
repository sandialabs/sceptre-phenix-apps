import json
import signal
import threading
import time
from typing import Any

from pydantic import Field

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import MetadataBlock, PositiveSeconds
from phenix_apps.common.logger import logger


class HostStatsMetadata(MetadataBlock):
    """Metadata for the hoststats component; see README.md for each field."""

    pollPeriod: PositiveSeconds = 5.0
    # None, or anything shorter than pollPeriod (even 0), means "every poll"
    flushPeriod: float | None = Field(None, allow_inf_nan=False)
    # read by phenix, not by this component
    filebeat_inputs: list[dict[str, Any]] | None = Field(None, alias="filebeat.inputs")

    @property
    def flush_every(self) -> int:
        """Polls between flushes to host_stats.jsonl (at least 1)."""
        flush = max(self.flushPeriod or self.pollPeriod, self.pollPeriod)
        return int(flush / self.pollPeriod)


class HostStats(ComponentBase):
    metadata_model = HostStatsMetadata
    config: HostStatsMetadata

    def __init__(self):
        ComponentBase.__init__(self, "hoststats")

        self.resdata = []
        self.stopped = threading.Event()

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        thread = threading.Thread(target=self.__run_monitor)
        thread.start()

        logger.info(f"Started user component: {self.name}")

        # wait for calling process to send SIGTERM
        signal.pause()
        # phenix kills the process 10 s after SIGTERM, so the monitor must wake
        # now rather than finish a long pollPeriod sleep before the last flush
        self.stopped.set()

        logger.info(f"Stopping user component: {self.name}")

        thread.join()
        self.__flush_buffer()

        logger.info(f"Stopped user component: {self.name}")

    def __run_monitor(self):
        count = 0

        while not self.stopped.is_set():
            # one failed poll (minimega busy or restarting) must not end the
            # collection for the rest of the run
            try:
                data = self.__get_resdata()
            except Exception as ex:
                logger.warning(f"host stats poll failed, will retry: {ex}")
                data = []

            if data:
                self.resdata.extend(data)

            if count % self.config.flush_every == 0:
                self.__flush_buffer()

            self.stopped.wait(self.config.pollPeriod)
            count += 1

    def __flush_buffer(self):
        if not self.resdata:
            return

        output_file = self.base_dir / "host_stats.jsonl"

        # write jsonl
        with output_file.open("a+") as f:
            for datum in self.resdata:
                json_record = json.dumps(datum)
                f.write(json_record + "\n")

        # clear buffer
        self.resdata = []

    def __get_resdata(self):
        resdata = []
        host_vms = {}
        vm_info = self.mm.vm_info()

        try:
            for host in vm_info:
                name_indx = host["Header"].index("name")
                host_vms[host["Host"]] = []

                for vm in host["Tabular"]:
                    host_vms[host["Host"]].append(vm[name_indx])
        except TypeError:
            pass

        host_info = self.mm.host()

        logger.info(f"getting host data for {len(vm_info)} hosts")
        try:
            for host in host_info:
                host_dict = {}

                host_dict["compute_name"] = host["Data"].pop("Name")
                host_dict.update(host["Data"])

                loads = host_dict.pop("Load").split()

                host_dict["Load_1"] = float(loads[0])
                host_dict["Load_5"] = float(loads[1])
                host_dict["Load_15"] = float(loads[2])

                host_dict["timestamp"] = int(time.time() * 1000)  # milliseconds
                host_dict["vm_list"] = sorted(
                    host_vms.get(host_dict["compute_name"], [])
                )

                resdata.append(host_dict)
        except TypeError:
            return []

        # A one-line summary per sample for the UI modal; the full records go to
        # host_stats.jsonl. Logging them whole made multi-KB lines every poll.
        logger.info(
            "; ".join(
                f"{h['compute_name']}: load {h['Load_1']}, {len(h['vm_list'])} VMs"
                for h in resdata
            )
        )
        return resdata


def main():
    HostStats()


if __name__ == "__main__":
    main()
