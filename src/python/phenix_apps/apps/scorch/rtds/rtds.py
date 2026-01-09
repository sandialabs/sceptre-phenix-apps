import sys
from pathlib import PurePath
from time import sleep

import requests
from elasticsearch import Elasticsearch

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class RTDS(ComponentBase):
    """
    SCORCH component for the Real-Time Dynamic Simulator (RTDS) bennu provider.
    """

    def __init__(self):
        ComponentBase.__init__(self, "rtds")

        # Ensure proxy variables from environment are ignored (e.g. "http_proxy")
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.verify = False

        self.execute_stage()

    def _start_case(self):
        """
        Start simulation on the RTDS. This sends a POST request to the GUI automation script running on the
        computer running RSCAD FX.
        """
        url = f"{self.metadata.rscad_automation.url.rstrip('/')}/start_case"
        self.print(f"Starting RSCAD case, url={url}")

        resp = self.session.post(url)

        if not resp:
            self.eprint("Starting RSCAD case failed: no response from server")
            sys.exit(1)

        data = resp.json()
        if not data["success"]:
            self.eprint(f"Starting RSCAD case failed: {data['status']}")
            sys.exit(1)

        # TODO: if status == "already_running", stop case, then start again?

        # validation that correct case name started/stopped via case_file in the response
        if self.metadata.get("case_name"):
            case_name = PurePath(data["case_file"]).stem  # minus extension
            if self.metadata.case_name != case_name:
                self.eprint(
                    f"Expected RSCAD case '{self.metadata.case_name}', but '{case_name}' was started. Stopping case and exiting..."
                )
                self._stop_case(allow_failure=True)
                sys.exit(1)

        self.print(
            f"Started RSCAD case '{data['case_file']}' (title='{data['case_title']}', status='{data['status']}')"
        )

    def _stop_case(self, allow_failure: bool = False):
        url = f"{self.metadata.rscad_automation.url.rstrip('/')}/stop_case"
        self.print(f"Stopping RSCAD case, url={url}")

        resp = self.session.post(url)

        if not resp:
            self.eprint("Stopping RSCAD case failed: no response from server")
            if not allow_failure:
                sys.exit(1)

        data = resp.json()
        if not data["success"]:
            self.eprint(f"Stopping RSCAD case failed: {data['status']}")
            if not allow_failure:
                sys.exit(1)

        self.print(
            f"Stopped RSCAD case '{data['case_file']}' (title='{data['case_title']}', status='{data['status']}')"
        )

    def _stop_provider_if_running(self):
        if self.check_process_running(self.metadata.hostname, "pybennu-power-solver"):
            self.print("Stopping pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver stop"
            self.run_and_check_command(self.metadata.hostname, cmd)

    def _verify_frequency(self, index: str, time_range: str = "now-5s") -> None:
        self.print("Verifying frequency is expected in Elasticsearch")
        response = self.es.search(
            index=index,
            size=1,
            # time can get funky
            # TODO: use event.ingested instead of @timestamp?
            query={
                "bool": {"filter": [{"range": {"@timestamp": {"gte": time_range}}}]}
            },
        )

        if not response["hits"]["hits"]:
            self.eprint(
                "no data in response from elasticsearch! the provider might have be having issues."
            )
            sys.exit(1)

        measurements = response["hits"]["hits"][0]["_source"]["measurement"]
        frequency = measurements["frequency"]

        if frequency > 60.5 or frequency < 59.5:
            self.eprint(f"frequency out of bounds, expected 60 +-0.5, got {frequency}")
            sys.exit(1)

        self.print("frequency verified")

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        host = self.metadata.hostname  # type: str

        self.ensure_vm_running(host)

        # Copy provider configs
        if self.metadata.get("export_config", True):
            self.recv_file(
                vm=host,
                src=[
                    "/etc/sceptre/config.ini",
                    "/etc/sceptre/rtds_config.yaml",
                ],
            )

        self.print("verifying NTP is ok")
        ntp_output = self.run_and_check_command(host, "ntpq -p")["stdout"]
        if ntp_output is None or ".INIT." in ntp_output:
            self.eprint(
                f"ntp on provider in INIT state, not synced. ntpq output: {ntp_output}"
            )
            sys.exit(1)

        # Start simulation on the RTDS
        if self.metadata.get("rscad_automation", {}).get("enabled"):
            self._start_case()

        # Start provider
        self.print("ensuring provider is started")
        if not self.check_process_running(host, "pybennu-power-solver"):
            self.print("Starting pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver start -d"
            self.run_and_check_command(host, cmd)

            sleep_for = 8.0
            self.print(
                f"sleeping for {sleep_for} seconds to give provider time to start and reconnect to PMUs..."
            )
            sleep(sleep_for)

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        host = self.metadata.hostname  # type: str

        self.print("checking if provider is running")
        if not self.check_process_running(host, "pybennu-power-solver"):
            self.eprint("provider is not running!")
            sys.exit(1)

        # Verify CSV files
        if self.metadata.get("csv_files"):
            self.print("checking if CSV files exist")
            csv_path = self.metadata.csv_files.get("path", "/root/rtds_data")
            # TODO: check file sizes in output of ls to ensure they're being written to
            self.run_and_check_command(host, f"ls -lh {csv_path}")

        # Verify elasticsearch
        if self.metadata.get("elasticsearch", {}).get("verify"):
            self.print("Verifying data in Elasticsearch (elasticsearch.verify=true)")
            index = utils.get_dated_index(self.metadata.elasticsearch.index)

            # ** ground truth data being collected **
            self.print(
                f"Verifying ground truth data is being collected in Elasticsearch (index={index})"
            )
            sleep_for = 3.0
            self.print("Getting index doc count")
            doc_count_1 = self.es.indices.stats(index=index)["indices"][index]["total"][
                "docs"
            ]["count"]  # type: int

            self.print(
                f"Sleeping for {sleep_for} seconds to wait for data to be generated..."
            )
            sleep(sleep_for)  # wait 3 seconds

            self.print("Getting index doc count")
            doc_count_2 = self.es.indices.stats(index=index)["indices"][index]["total"][
                "docs"
            ]["count"]  # type: int

            self.print("Comparing doc counts")
            # 8 PMUs * 6 points * 30 updates/sec = 1440 docs/second
            # 3 seconds * 1440 = 4,320
            # There seems to be some delay though, so let's subtract 1 second
            expected_count_diff = (sleep_for - 1) * 1440
            count_diff = doc_count_2 - doc_count_1
            if count_diff < expected_count_diff:
                self.eprint(
                    f"expected {expected_count_diff} documents created, but only {count_diff} docs were created for index {index}"
                )
                sys.exit(1)
            self.print("ground truth data verified")

            # ** verify frequency is expected **
            # TODO: check angle and real values for each channel
            self._verify_frequency(index=index)

            # ** time drift between provider and RTDS is within acceptable limits **
            if self.metadata.elasticsearch.get("acceptable_time_drift"):
                acceptable = self.metadata.elasticsearch.acceptable_time_drift
                self.print(
                    f"Verifying time drift between RTDS and SCEPTRE environment is within an acceptable range (acceptable={acceptable})"
                )

                time_drift = get_time_drift(self.es, index, time_range="now-2m")
                if time_drift > acceptable:
                    self.eprint(
                        f"time drift of {time_drift} ms > configured acceptable drift "
                        f"of {acceptable} ms (index={index})"
                    )
                    sys.exit(1)
                self.print("time drift verified")

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        host = self.metadata.hostname  # type: str

        self._stop_provider_if_running()

        if self.metadata.get("rscad_automation", {}).get("enabled"):
            self._stop_case(allow_failure=False)

        # Copy CSV files
        if self.metadata.get("csv_files", {}).get("export"):
            src = self.metadata.csv_files.get("path", "/root/rtds_data")
            self.print(f"Saving CSV files from provider (src={src})")
            self.recv_file(host, src)

        # Copy provider log files
        if self.metadata.get("export_logs"):
            self.recv_file(
                vm=host,
                src=[
                    "/var/log/bennu-pybennu.out",
                    "/var/log/bennu-pybennu.err",
                ],
            )

        # Copy provider configs
        if self.metadata.get("export_config", True):
            self.recv_file(
                vm=host,
                src=[
                    "/etc/sceptre/config.ini",
                    "/etc/sceptre/rtds_config.yaml",
                ],
            )

        # # Verify Elasticsearch data
        # if self.metadata.get("elasticsearch", {}).get("verify"):
        #     index = utils.get_dated_index(self.metadata.elasticsearch.index)
        #     # TODO: configurable frequency check on stop
        #     # This doubles as a check for the data in Elastic
        #     self._verify_frequency(index=index, time_range="now-20s")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        host = self.metadata.hostname  # type: str

        self._stop_provider_if_running()

        # Delete CSV files
        if self.metadata.get("csv_files"):
            csv_path = self.metadata.csv_files.get("path", "/root/rtds_data")
            self.print(f"Deleting provider CSV files (path={csv_path})")
            utils.mm_exec_wait(self.mm, host, f"rm -rf {csv_path}")

        # Delete log files
        self.print("Deleting provider log files")
        utils.mm_delete_file(self.mm, f"name={host}", "/var/log/bennu-pybennu.out")
        utils.mm_delete_file(self.mm, f"name={host}", "/var/log/bennu-pybennu.err")

        # Ensure RSCAD is stopped, even if stop stage didn't get hit
        if self.metadata.get("rscad_automation", {}).get("enabled"):
            self._stop_case(allow_failure=True)

        logger.info(f"Cleaned up user component: {self.name}")


def get_time_drift(es: Elasticsearch, index: str, time_range: str = "now-5m") -> float:
    response = es.search(
        index=index,
        size=0,
        query={"bool": {"filter": [{"range": {"@timestamp": {"gte": time_range}}}]}},
        aggs={
            "timestamp_diff": {
                "avg": {
                    "script": """
ZonedDateTime d1 = doc['rtds_time'].value;
ZonedDateTime d2 = doc['sceptre_time'].value;
long differenceInMillis = ChronoUnit.MILLIS.between(d1, d2);
return Math.abs(differenceInMillis);
""".strip()
                }
            }
        },
    )

    return response["aggregations"]["timestamp_diff"]["value"]


def main():
    RTDS()


if __name__ == "__main__":
    main()
