import configparser
from pathlib import Path, PurePosixPath
from time import sleep
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    Field,
    PositiveFloat,
    PositiveInt,
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
from phenix_apps.common import error, utils
from phenix_apps.common.logger import logger


def _check_fetch_path(path: str) -> str:
    if ".." in PurePosixPath(path).parts:
        raise error.AppError(f"invalid provider config path '{path}'")
    return path


def _absolute(path: str) -> str:
    # spliced into rm/find on the provider, so keep it pinned to a real dir
    if not path.startswith("/") or ".." in PurePosixPath(path).parts:
        raise ValueError("must be an absolute path without '..'")
    return str(PurePosixPath(path))


AbsPath = Annotated[FilePath, AfterValidator(_absolute)]


class ElasticsearchConfig(MetadataBlock):
    verify: bool = False
    server: AnyHttpUrl | None = None
    index: Token | None = None
    # fewest documents the index may hold for start to pass
    min_documents: PositiveInt = 100
    # opt-in: fewest documents that must arrive during doc_count_wait
    min_new_documents: PositiveInt | None = None
    doc_count_wait: PositiveSeconds = 3.0
    # opt-in: expected grid frequency (Hz) of the newest measurement
    expected_frequency: PositiveFloat | None = None
    frequency_tolerance: PositiveFloat = 0.5

    @model_validator(mode="after")
    def _needed_when_verifying(self) -> Self:
        if self.verify:
            missing = [f for f in ("server", "index") if getattr(self, f) is None]
            if missing:
                raise ValueError(
                    f"{' and '.join(missing)} required when verify is true"
                )
        return self


class CsvFiles(MetadataBlock):
    path: AbsPath = "/root/provider_data"
    export: bool = False
    # seconds between the two size readings that prove the files are growing
    growth_wait: PositiveSeconds = 3.0


class ProviderDataMetadata(MetadataBlock):
    """Metadata for the providerdata component; see README.md for each field.

    A MetadataBlock, so unknown keys are warned about; the collector reads this
    component's output files, not this block.
    """

    hostname: Hostname
    export_logs: bool = False
    export_config: bool = True
    # seconds to let pybennu-power-solver start and reconnect to its PMUs
    start_wait: Seconds = 8.0
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)
    csv_files: CsvFiles | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_csv_files_means_off(cls, data: Any) -> Any:
        # An empty csv_files block has always meant "no CSV handling"; without
        # this it would become CsvFiles() and turn the CSV check on.
        if isinstance(data, dict) and data.get("csv_files") == {}:
            data = {**data, "csv_files": None}
        return data


class ProviderData(ComponentBase):
    """
    SCORCH component for data collection from generalized bennu provider.
    Intended to work with any bennu provider, but needs testing.
    """

    metadata_model = ProviderDataMetadata
    config: ProviderDataMetadata

    def __init__(self):
        ComponentBase.__init__(self, "providerdata")
        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        host = self.config.hostname

        self.ensure_vm_running(host)

        # Copy provider configs
        if self.config.export_config:
            self._export_config(host)

        logger.info("verifying NTP is ok")
        ntp_output = self.run_and_check_command(host, "ntpq -p")["stdout"]
        if ntp_output is None or ".INIT." in ntp_output:
            raise RuntimeError(
                f"ntp on provider in INIT state, not synced. ntpq output: {ntp_output}"
            )

        # Start provider
        logger.info("ensuring provider is started")
        if not self.check_process_running(host, "pybennu-power-solver"):
            logger.info("Starting pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver -d start"
            self.run_and_check_command(host, cmd)

            sleep_for = self.config.start_wait
            logger.info(
                f"sleeping for {sleep_for} seconds to give provider time to start and reconnect to PMUs..."
            )
            sleep(sleep_for)

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        host = self.config.hostname

        logger.info("checking if provider is running")
        if not self.check_process_running(host, "pybennu-power-solver"):
            raise RuntimeError("provider is not running!")

        # Verify CSV files
        if self.config.csv_files:
            logger.info("checking if CSV files exist")
            csv_path = self.config.csv_files.path
            self.run_and_check_command(host, f"ls -lh {csv_path}")
            self._verify_csv_growth(host, csv_path, self.config.csv_files.growth_wait)

        # Verify elasticsearch
        logger.info(f"{self.name}: checking ES")
        es_config = self.config.elasticsearch
        if es_config.verify:
            logger.info("Verifying data in Elasticsearch (elasticsearch.verify=true)")
            if es_config.index is None:  # the model requires it when verifying
                raise ValueError("elasticsearch.index is required when verifying")
            index = utils.get_dated_index(es_config.index)

            # ** ground truth data being collected **
            logger.info(
                f"Verifying ground truth data is being collected in Elasticsearch (index={index})"
            )
            logger.info("Getting index doc count")
            doc_count_1 = self._doc_count(index)
            logger.info(f"ES doc count is: {doc_count_1}")

            if doc_count_1 < es_config.min_documents:
                msg = (
                    f"only {doc_count_1} documents in {index} (expected at least "
                    f"{es_config.min_documents}); the provider does not appear to "
                    "be sending data"
                )
                logger.error(f"{self.name}: {msg}")
                raise RuntimeError(msg)

            if es_config.min_new_documents is not None:
                self._verify_doc_rate(index, es_config.min_new_documents)
            if es_config.expected_frequency is not None:
                self._verify_frequency(index, es_config.expected_frequency)

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        host = self.config.hostname

        # Copy CSV files
        if self.config.csv_files and self.config.csv_files.export:
            src = str(self.config.csv_files.path)
            logger.info(f"Saving CSV files from provider (src={src})")
            self.recv_file(host, src)

        # Copy provider log files
        if self.config.export_logs:
            self.recv_file(
                vm=host,
                src=[
                    "/var/log/bennu-pybennu.out",
                    "/var/log/bennu-pybennu.err",
                ],
            )

        # Copied again because the collector reads this loop's folder, and
        # configure may have run outside the loop, in another folder.
        if self.config.export_config:
            self._export_config(host)

        logger.info(f"Stopped user component: {self.name}")

    def _csv_bytes(self, host: str, path: str) -> int:
        out = self.run_and_check_command(host, f"find {path} -type f -printf '%s\\n'")
        return sum(int(n) for n in (out["stdout"] or "").split())

    def _verify_csv_growth(self, host: str, path: str, wait: float) -> None:
        before = self._csv_bytes(host, path)
        logger.info(f"waiting {wait} seconds to see the CSV files grow")
        sleep(wait)
        after = self._csv_bytes(host, path)
        if after <= before:
            raise RuntimeError(
                f"CSV files in {path} on {host} did not grow in {wait} seconds "
                f"({before} bytes); the provider does not appear to be writing them"
            )
        logger.info(f"CSV files grew by {after - before} bytes")

    def _doc_count(self, index: str) -> int:
        return self.es.indices.stats(index=index)["indices"][index]["total"]["docs"][
            "count"
        ]

    def _verify_doc_rate(self, index: str, minimum: int) -> None:
        es_config = self.config.elasticsearch
        before = self._doc_count(index)
        logger.info(f"waiting {es_config.doc_count_wait} seconds for new documents")
        sleep(es_config.doc_count_wait)
        new = self._doc_count(index) - before
        if new < minimum:
            raise RuntimeError(
                f"only {new} new documents in {index} after "
                f"{es_config.doc_count_wait} seconds (expected at least {minimum})"
            )
        logger.info(f"{new} new documents in {index}")

    def _verify_frequency(self, index: str, expected: float) -> None:
        es_config = self.config.elasticsearch
        response = self.es.search(
            index=index,
            size=1,
            sort=[{"@timestamp": "desc"}],
            query={"range": {"@timestamp": {"gte": "now-5s"}}},
        )
        hits = response["hits"]["hits"]
        if not hits:
            raise RuntimeError(f"no documents in {index} in the last 5 seconds")
        frequency = hits[0]["_source"]["measurement"]["frequency"]
        if abs(frequency - expected) > es_config.frequency_tolerance:
            raise RuntimeError(
                f"frequency out of bounds, expected {expected} "
                f"+-{es_config.frequency_tolerance}, got {frequency}"
            )
        logger.info(f"frequency {frequency} verified")

    def _export_config(self, host: str) -> None:
        """Copy config.ini, then the YAML config it names, from the provider."""

        logger.info(f"reading provider configs from '{host}'")
        self.recv_file(vm=host, src="/etc/sceptre/config.ini")
        pconf = configparser.ConfigParser()
        pconf.read(Path(self.base_dir) / "config.ini")

        try:
            config_file = pconf.get(
                section="power-solver-service", option="config-file"
            )
        except configparser.Error as ex:
            raise RuntimeError(
                f"/etc/sceptre/config.ini on {host} does not name the provider's "
                f"config file ([power-solver-service] config-file): {ex}"
            ) from ex

        # read the yaml file based on what's in the config
        self.recv_file(vm=host, src=_check_fetch_path(config_file))


def main():
    ProviderData()


if __name__ == "__main__":
    main()
