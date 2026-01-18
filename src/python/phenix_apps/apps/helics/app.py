import os
import sys

from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Helics(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.helics_dir: str = f"{self.exp_dir}/helics"
        os.makedirs(self.helics_dir, exist_ok=True)

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        broker_md = self.metadata.get("broker", {})
        root = broker_md.get("root", None)

        if not root:
            logger.error("no root broker provided, but required")
            sys.exit(1)

        if "|" in root:  # hostname|iface
            root_hostname, iface = root.split("|", 1)

            root_ip = self.extract_node_interface_ip(root_hostname, iface)

            if not root_ip:
                logger.error(f"root broker not found in topology: {root_hostname}")
                sys.exit(1)
        else:  # ip[:port]
            root_ip = root

        if ":" in root_ip:  # silently ignore port if provided
            root_ip, _ = root_ip.split(":", 1)

        root_hostname = self.extract_node_hostname_for_ip(root_ip)

        if not root_hostname:
            logger.error(f"root broker not found in topology: {root}")
            sys.exit(1)

        if not self.is_booting(root_hostname):
            logger.error(f"root broker is marked do not boot: {root_hostname}")

        self.add_label(root_hostname, "group", "helics")
        self.add_label(root_hostname, "helics", "broker")

        # create the wait script to be injected into federates
        templates = utils.abs_path(__file__, "templates/")
        wait_file = f"{self.helics_dir}/wait-broker.sh"
        with open(wait_file, "w") as f:
            utils.mako_serve_template(
                "wait_broker.mako", templates, f, rootbroker_ip=root_ip
            )

        total_fed_count = 0

        # broker hosts --> ip:port --> ['fed_count', 'log_level']
        # hosts to create start scripts for, ip:port combos to create sub brokers for
        brokers = {}
        federates = self.extract_annotated_topology_nodes("helics/federate")

        for fed in federates:
            if not self.is_booting(fed.general.hostname):
                continue

            self.add_label(fed.general.hostname, "group", "helics")
            self.add_label(fed.general.hostname, "helics", "federate")
            configs = fed.annotations.get("helics/federate", [])

            # if the federate has the helics/federate annotation, add the inject to wait for the broker
            if configs and configs[0].get("broker-wait", True):
                dst = "/etc/phenix/startup/5-wait-broker.sh"
                self.add_inject(
                    hostname=fed.general.hostname, inject={"src": wait_file, "dst": dst}
                )

            for config in configs:
                broker = config.get("broker", "127.0.0.1")
                count = config.get("fed-count", 1)
                level = config.get("log-level", "SUMMARY")

                total_fed_count += count

                if "|" in broker:  # hostname|iface
                    broker_hostname, iface = broker.split("|", 1)
                    broker_ip = self.extract_node_interface_ip(broker_hostname, iface)

                    if not broker_ip:
                        logger.error(f"broker not found in topology: {broker_hostname}")
                        sys.exit(1)
                else:  # ip[:port]
                    broker_ip = broker

                if broker_ip == root_ip:
                    # not connecting to sub broker
                    continue

                if ":" not in broker_ip:
                    # default to port 24000 for sub broker
                    broker_ip += ":24000"

                hostname = self.extract_node_hostname_for_ip(broker_ip)

                if not hostname:
                    logger.error(f"node not found for broker at {broker}")
                    sys.exit(1)

                if not self.is_booting(hostname):
                    logger.error(f"broker node is marked do not boot: {hostname}")

                self.add_label(hostname, "group", "helics")
                self.add_label(hostname, "helics", "broker")

                entry = brokers.get(hostname, {broker_ip: [0, None]})
                entry[broker][0] += count

                # only overwrite the log level if it wasn't already set
                if entry[broker][1] is None:
                    entry[broker][1] = level

                brokers[hostname] = entry

        log_dir = broker_md.get("log-dir", "/var/log")

        root_broker_config = {
            "name": root_hostname,
            "subs": 0,
            "feds": total_fed_count,
            "endpoint": root_ip,
            "log-level": broker_md.get("log-level", "summary"),
            "log-file": os.path.join(log_dir, "helics-root-broker.log"),
        }

        # per-host broker configs, initialized with root broker
        configs = {root_hostname: [root_broker_config]}

        for hostname, subs in brokers.items():
            # just in case hostname is root broker, which was initialized above
            broker_configs = configs.get(hostname, [])

            # individual sub brokers for host (there will usually just be one)
            for endpoint, fedinfo in subs.items():
                root_broker_config["subs"] += 1

                count = fedinfo[0]
                level = fedinfo[1]

                broker_configs.append(
                    {
                        "name": hostname,
                        "feds": count,
                        "parent": root_ip,
                        "endpoint": endpoint,
                        "log-level": level,
                        "log-file": os.path.join(log_dir, "helics-sub-broker.log"),
                    }
                )

            configs[hostname] = broker_configs

        for hostname, broker_configs in configs.items():
            start_file = f"{self.helics_dir}/{hostname}-broker.sh"

            with open(start_file, "w") as f:
                utils.mako_serve_template(
                    "broker.mako", templates, f, configs=broker_configs
                )

            dst = "/etc/phenix/startup/90-helics-broker.sh"
            self.add_inject(hostname=hostname, inject={"src": start_file, "dst": dst})
