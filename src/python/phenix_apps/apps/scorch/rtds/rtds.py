import re
from pathlib import PureWindowsPath
from time import sleep
from typing import Annotated, Any, Self

import requests
from elasticsearch import Elasticsearch
from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    Field,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    MetadataBlock,
    PositiveSeconds,
    Seconds,
    Token,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


def _deletable_dir(path: str) -> str:
    # cleanup runs `rm -rf <path>` in a shell on the provider, so it must be an
    # absolute directory below / (FilePath already rules out shell syntax and
    # globs): no '.' or '..' segments, and not / itself.
    segments = path.split("/")
    if not path.startswith("/") or not path.strip("/") or {".", ".."} & set(segments):
        raise ValueError(
            "must be an absolute directory below / with no '.' or '..' segments"
        )
    return path


CsvDir = Annotated[FilePath, AfterValidator(_deletable_dir)]


# The case file is named after the case, and the RSCAD automation server runs
# on Windows. The component compares the name to the stem of the started
# case_file, so it must be a bare Windows file name without the extension.
_CASE_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CASE_EXTENSIONS = (".rtfx", ".rtf")


def _case_name(name: str) -> str:
    if _CASE_FORBIDDEN.search(name):
        raise ValueError(
            'must be a bare file name without path separators or any of < > : " | ? *'
        )
    if name.lower().endswith(_CASE_EXTENSIONS):
        raise ValueError("must not include the file extension")
    if name != name.rstrip(". "):
        raise ValueError("must not end with a space or '.'")
    return name


CaseName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    AfterValidator(_case_name),
]


# AnyHttpUrl gives a bare host a trailing slash; store the URL without one.
RscadUrl = Annotated[AnyHttpUrl, AfterValidator(lambda u: str(u).rstrip("/"))]


class RscadAutomation(MetadataBlock):
    enabled: bool = False
    url: RscadUrl | None = None
    case_name: CaseName | None = None
    timeout: PositiveSeconds = 30.0

    @model_validator(mode="after")
    def _url_when_enabled(self) -> Self:
        if self.enabled and self.url is None:
            raise ValueError("url is required when enabled is true")
        return self


class ElasticsearchConfig(MetadataBlock):
    verify: bool = False
    server: AnyHttpUrl | None = None
    index: Token | None = None
    acceptable_time_drift: float | None = Field(None, gt=0, allow_inf_nan=False)
    # Seconds between the two document counts; at least (doc_count_wait - 1) *
    # 1440 new documents must arrive, so it must be more than 1.
    doc_count_wait: float = Field(3.0, gt=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _server_and_index_when_verifying(self) -> Self:
        if self.verify:
            missing = [f for f in ("server", "index") if getattr(self, f) is None]
            if missing:
                raise ValueError(
                    f"{' and '.join(missing)} required when verify is true"
                )
        return self


class CsvFiles(MetadataBlock):
    path: CsvDir = "/root/rtds_data"
    export: bool = False


class RTDSMetadata(MetadataBlock):
    """Metadata for the rtds component; see README.md for each field."""

    hostname: Hostname
    export_logs: bool = False
    export_config: bool = True
    provider_start_wait: Seconds = 8.0
    rscad_automation: RscadAutomation = RscadAutomation()
    elasticsearch: ElasticsearchConfig = ElasticsearchConfig()
    csv_files: CsvFiles | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_csv_files_means_off(cls, data: Any) -> Any:
        # An empty csv_files block always meant "no CSV handling"; without this
        # it would become CsvFiles() and cleanup would delete the default path.
        if isinstance(data, dict) and data.get("csv_files") == {}:
            data = {**data, "csv_files": None}
        return data


class RTDS(ComponentBase):
    """
    SCORCH component for the Real-Time Dynamic Simulator (RTDS) bennu provider.
    """

    metadata_model = RTDSMetadata
    config: RTDSMetadata

    def __init__(self):
        ComponentBase.__init__(self, "rtds")

        # Ensure proxy variables from environment are ignored (e.g. "http_proxy")
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.verify = False

        self.execute_stage()

    def _rscad_endpoint(self, name: str) -> str:
        return f"{self.config.rscad_automation.url}/{name}"

    def _start_case(self):
        """
        Start simulation on the RTDS. This sends a POST request to the GUI automation script running on the
        computer running RSCAD FX.
        """
        url = self._rscad_endpoint("start_case")
        logger.info(f"Starting RSCAD case, url={url}")

        resp = self.session.post(url, timeout=self.config.rscad_automation.timeout)

        if not resp:
            raise RuntimeError(
                f"Starting RSCAD case failed: HTTP {resp.status_code} from {url}"
            )

        data = resp.json()
        if not data["success"]:
            raise RuntimeError(f"Starting RSCAD case failed: {data['status']}")

        # TODO: if status == "already_running", stop case, then start again?

        # validation that correct case name started/stopped via case_file in the response
        expected = self.config.rscad_automation.case_name
        if expected:
            case_name = PureWindowsPath(data["case_file"]).stem  # minus extension
            if expected != case_name:
                logger.error(
                    f"Expected RSCAD case '{expected}', but '{case_name}' was started. Stopping case and exiting..."
                )
                self._stop_case(allow_failure=True)
                raise RuntimeError(
                    f"Expected RSCAD case '{expected}', but '{case_name}' was started"
                )

        logger.info(
            f"Started RSCAD case '{data['case_file']}' (title='{data['case_title']}', status='{data['status']}')"
        )

    def _stop_case(self, allow_failure: bool = False):
        url = self._rscad_endpoint("stop_case")
        logger.info(f"Stopping RSCAD case, url={url}")

        try:
            resp = self.session.post(url, timeout=self.config.rscad_automation.timeout)
            if not resp:
                raise RuntimeError(
                    f"Stopping RSCAD case failed: HTTP {resp.status_code} from {url}"
                )
            data = resp.json()
            if not data["success"]:
                raise RuntimeError(f"Stopping RSCAD case failed: {data['status']}")
        except Exception as ex:
            if not allow_failure:
                raise
            logger.warning(f"{ex} (ignored, allow_failure=True)")
            return

        logger.info(
            f"Stopped RSCAD case '{data['case_file']}' (title='{data['case_title']}', status='{data['status']}')"
        )

    def _stop_provider_if_running(self):
        if self.check_process_running(self.config.hostname, "pybennu-power-solver"):
            logger.info("Stopping pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver stop"
            self.run_and_check_command(self.config.hostname, cmd)

    def _verify_frequency(self, index: str, time_range: str = "now-5s") -> None:
        logger.info("Verifying frequency is expected in Elasticsearch")
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
            raise RuntimeError(
                "no data in response from elasticsearch! the provider might be having issues."
            )

        measurements = response["hits"]["hits"][0]["_source"]["measurement"]
        frequency = measurements["frequency"]

        if frequency > 60.5 or frequency < 59.5:
            raise RuntimeError(
                f"frequency out of bounds, expected 60 +-0.5, got {frequency}"
            )

        logger.info("frequency verified")

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        self.ensure_vm_running(self.config.hostname)

        # Copy provider configs
        if self.config.export_config:
            self.recv_file(
                vm=self.config.hostname,
                src=[
                    "/etc/sceptre/config.ini",
                    "/etc/sceptre/rtds_config.yaml",
                ],
            )

        logger.info("verifying NTP is ok")
        ntp_output = self.run_and_check_command(self.config.hostname, "ntpq -p")[
            "stdout"
        ]
        if ntp_output is None or ".INIT." in ntp_output:
            raise RuntimeError(
                f"ntp on provider in INIT state, not synced. ntpq output: {ntp_output}"
            )

        # Start simulation on the RTDS
        if self.config.rscad_automation.enabled:
            self._start_case()

        # Start provider
        logger.info("ensuring provider is started")
        if not self.check_process_running(self.config.hostname, "pybennu-power-solver"):
            logger.info("Starting pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver start -d"
            self.run_and_check_command(self.config.hostname, cmd)

            logger.info(
                f"sleeping for {self.config.provider_start_wait} seconds to give provider time to start and reconnect to PMUs..."
            )
            sleep(self.config.provider_start_wait)

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        logger.info("checking if provider is running")
        if not self.check_process_running(self.config.hostname, "pybennu-power-solver"):
            raise RuntimeError("provider is not running!")

        # Verify CSV files
        if self.config.csv_files:
            logger.info("checking if CSV files exist")
            # TODO: check file sizes in output of ls to ensure they're being written to
            self.run_and_check_command(
                self.config.hostname, f"ls -lh {self.config.csv_files.path}"
            )

        # Verify elasticsearch
        if self.config.elasticsearch.verify:
            logger.info("Verifying data in Elasticsearch (elasticsearch.verify=true)")
            if (
                self.config.elasticsearch.index is None
            ):  # the model requires it when verifying
                raise ValueError("elasticsearch.index is required when verifying")
            index = utils.get_dated_index(self.config.elasticsearch.index)

            # ** ground truth data being collected **
            logger.info(
                f"Verifying ground truth data is being collected in Elasticsearch (index={index})"
            )
            logger.info("Getting index doc count")
            doc_count_1 = self.es.indices.stats(index=index)["indices"][index]["total"][
                "docs"
            ]["count"]

            logger.info(
                f"Sleeping for {self.config.elasticsearch.doc_count_wait} seconds to wait for data to be generated..."
            )
            sleep(self.config.elasticsearch.doc_count_wait)

            logger.info("Getting index doc count")
            doc_count_2 = self.es.indices.stats(index=index)["indices"][index]["total"][
                "docs"
            ]["count"]

            logger.info("Comparing doc counts")
            # 8 PMUs * 6 points * 30 updates/sec = 1440 docs/second
            # 3 seconds * 1440 = 4,320
            # There seems to be some delay though, so let's subtract 1 second
            expected_count_diff = (self.config.elasticsearch.doc_count_wait - 1) * 1440
            count_diff = doc_count_2 - doc_count_1
            if count_diff < expected_count_diff:
                raise RuntimeError(
                    f"expected {expected_count_diff} documents created, but only {count_diff} docs were created for index {index}"
                )
            logger.info("ground truth data verified")

            # ** verify frequency is expected **
            # TODO: check angle and real values for each channel
            self._verify_frequency(index=index)

            # ** time drift between provider and RTDS is within acceptable limits **
            if self.config.elasticsearch.acceptable_time_drift is not None:
                logger.info(
                    f"Verifying time drift between RTDS and SCEPTRE environment is within an acceptable range (acceptable={self.config.elasticsearch.acceptable_time_drift})"
                )

                time_drift = get_time_drift(self.es, index, time_range="now-2m")
                if time_drift > self.config.elasticsearch.acceptable_time_drift:
                    raise RuntimeError(
                        f"time drift of {time_drift} ms > configured acceptable drift "
                        f"of {self.config.elasticsearch.acceptable_time_drift} ms (index={index})"
                    )
                logger.info("time drift verified")

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        self._stop_provider_if_running()

        if self.config.rscad_automation.enabled:
            self._stop_case(allow_failure=False)

        # Copy CSV files
        if self.config.csv_files and self.config.csv_files.export:
            logger.info(
                f"Saving CSV files from provider (src={self.config.csv_files.path})"
            )
            self.recv_file(self.config.hostname, self.config.csv_files.path)

        # Copy provider log files
        if self.config.export_logs:
            self.recv_file(
                vm=self.config.hostname,
                src=[
                    "/var/log/bennu-pybennu.out",
                    "/var/log/bennu-pybennu.err",
                ],
            )

        # Copy provider configs
        if self.config.export_config:
            self.recv_file(
                vm=self.config.hostname,
                src=[
                    "/etc/sceptre/config.ini",
                    "/etc/sceptre/rtds_config.yaml",
                ],
            )

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        self._stop_provider_if_running()

        # Delete CSV files
        if self.config.csv_files:
            logger.info(
                f"Deleting provider CSV files (path={self.config.csv_files.path})"
            )
            utils.mm_exec_wait(
                self.mm, self.config.hostname, f"rm -rf {self.config.csv_files.path}"
            )

        # Delete log files
        logger.info("Deleting provider log files")
        utils.mm_delete_file(
            self.mm, f"name={self.config.hostname}", "/var/log/bennu-pybennu.out"
        )
        utils.mm_delete_file(
            self.mm, f"name={self.config.hostname}", "/var/log/bennu-pybennu.err"
        )

        # Ensure RSCAD is stopped, even if stop stage didn't get hit
        if self.config.rscad_automation.enabled:
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

    drift = response["aggregations"]["timestamp_diff"]["value"]
    if drift is None:
        raise RuntimeError(
            f"no documents with rtds_time and sceptre_time in {index} since "
            f"{time_range}, cannot check time drift"
        )
    return drift


def main():
    RTDS()


if __name__ == "__main__":
    main()
