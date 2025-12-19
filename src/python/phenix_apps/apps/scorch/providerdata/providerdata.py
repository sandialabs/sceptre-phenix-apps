import configparser
import os.path
import sys
from time import sleep

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class ProviderData(ComponentBase):
    """
    SCORCH component for data collection from generalized bennu provider.
    Intended to work with any bennu provider, but needs testing.
    """

    def __init__(self):
        ComponentBase.__init__(self, 'providerdata')
        self.execute_stage()

    def configure(self):
        logger.info(f'Configuring user component: {self.name}')

        host = self.metadata.hostname  # type: str

        self.ensure_vm_running(host)

        # Copy provider configs
        if self.metadata.get("export_config", True):
            self.print(f"reading provider configs from '{host}'")
            # get the ini config
            self.recv_file(vm=host, src="/etc/sceptre/config.ini")
            pconf = configparser.ConfigParser()
            pconf.read(os.path.join(self.base_dir, "config.ini"))

            # read the yaml file based on what's in the config
            config_path = pconf.get(section="power-solver-service", option="config-file")
            self.recv_file(vm=host, src=config_path)

        self.print("verifying NTP is ok")
        ntp_output = self.run_and_check_command(host, "ntpq -p")["stdout"]
        if ntp_output is None or ".INIT." in ntp_output:
            self.eprint(f"ntp on provider in INIT state, not synced. ntpq output: {ntp_output}")
            sys.exit(1)

        # Start provider
        self.print("ensuring provider is started")
        if not self.check_process_running(host, "pybennu-power-solver"):
            self.print("Starting pybennu-power-solver")
            cmd = "/usr/local/bin/pybennu-power-solver -d start"
            self.run_and_check_command(host, cmd)

            sleep_for = 8.0
            self.print(f"sleeping for {sleep_for} seconds to give provider time to start and reconnect to PMUs...")
            sleep(sleep_for)

        logger.info(f'Configured user component: {self.name}')

    def start(self):
        logger.info(f'Starting user component: {self.name}')

        host = self.metadata.hostname  # type: str

        self.print("checking if provider is running")
        if not self.check_process_running(host, "pybennu-power-solver"):
            self.eprint("provider is not running!")
            sys.exit(1)

        # Verify CSV files
        if self.metadata.get("csv_files"):
            self.print("checking if CSV files exist")
            csv_path = self.metadata.csv_files.get("path", "/root/provider_data")
            # TODO: check file sizes in output of ls to ensure they're being written to
            self.run_and_check_command(host, f"ls -lh {csv_path}")

        # Verify elasticsearch
        logger.info(f'{self.name}: checking ES')
        if self.metadata.get("elasticsearch", {}).get("verify"):
            self.print("Verifying data in Elasticsearch (elasticsearch.verify=true)")
            index = utils.get_dated_index(self.metadata.elasticsearch.index)

            # ** ground truth data being collected **
            self.print(f"Verifying ground truth data is being collected in Elasticsearch (index={index})")
            # sleep_for = 3.0
            self.print("Getting index doc count")
            doc_count_1 = self.es.indices.stats(index=index)["indices"][index]["total"]["docs"]["count"]  # type: int
            self.print(f"ES doc count is: {doc_count_1}")

            # For now, just make sure there are docs getting to ES
            # TODO figure out how to verify frequency is correct for generalized bennu provider
            if doc_count_1 < 100:
                self.eprint("Elasticsearch does not appear to be running, exiting...")
                logger.error(f'{self.name}: Elasticsearch does not appear to be running, exiting...')
                sys.exit(1)

            # TODO: compare doc count after certain amount of time, use es.indices.stats()

        logger.info(f'Started user component: {self.name}')

    def stop(self):
        logger.info(f'Stopping user component: {self.name}')

        host = self.metadata.hostname  # type: str

        # Copy CSV files
        if self.metadata.get("csv_files", {}).get("export"):
            src = self.metadata.csv_files.get("path", "/root/provider_data")
            self.print(f"Saving CSV files from provider (src={src})")
            self.recv_file(host, src)

        # Copy provider log files
        if self.metadata.get("export_logs"):
            self.recv_file(vm=host, src=[
                "/var/log/bennu-pybennu.out",
                "/var/log/bennu-pybennu.err",
            ])

        # TODO: doing copy here as well so it's available to collector, stupid loop numbers...
        # Copy provider configs
        if self.metadata.get("export_config", True):
            self.print(f"reading provider configs from '{host}'")
            # get the ini config
            self.recv_file(vm=host, src="/etc/sceptre/config.ini")
            pconf = configparser.ConfigParser()
            pconf.read(os.path.join(self.base_dir, "config.ini"))

            # read the yaml file based on what's in the config
            config_path = pconf.get(section="power-solver-service", option="config-file")
            self.recv_file(vm=host, src=config_path)

        logger.info(f'Stopped user component: {self.name}')


def main():
    ProviderData()


if __name__ == '__main__':
    main()
