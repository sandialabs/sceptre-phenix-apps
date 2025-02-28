import os, sys

from phenix_apps.apps   import AppBase
from phenix_apps.common import logger, utils

class Helics(AppBase):
    def __init__(self):
        AppBase.__init__(self, 'helics')

        self.helics_dir = f"{self.exp_dir}/helics"
        os.makedirs(self.helics_dir, exist_ok=True)

        self.execute_stage()

        # We don't (currently) let the parent AppBase class handle this step
        # just in case app developers want to do any additional manipulation
        # after the appropriate stage function has completed.
        print(self.experiment.to_json())

    def pre_start(self):
        logger.log('INFO', f'Starting user application: {self.name}')

        broker_md = self.metadata.get('broker', {})
        root      = broker_md.get('root', None)

        if not root:
            logger.log('ERROR', 'no root broker provided, but required')
            sys.exit(1)

        if '|' in root: # hostname|iface
            root_hostname, iface = root.split('|', 1)

            root_ip = self.extract_node_interface_ip(root_hostname, iface)

            if not root_ip:
                logger.log('ERROR', f'root broker not found in topology: {root_hostname}')
                sys.exit(1)
        else: # ip[:port]
            root_ip = root

        if ':' in root_ip: # silently ignore port if provided
            root_ip, _ = root_ip.split(':', 1)

        root_hostname = self.extract_node_hostname_for_ip(root_ip)

        if not root_hostname:
            logger.log('ERROR', f'root broker not found in topology: {root}')
            sys.exit(1)

        if not self.is_booting(root_hostname):
            logger.log('ERROR', f'root broker is marked do not boot: {root_hostname}')

        self.add_label(root_hostname, 'group', 'helics')
        self.add_label(root_hostname, 'helics', 'broker')

        total_fed_count = 0

        # broker hosts --> ip:port --> fed-count
        # hosts to create start scripts for, ip:port combos to create sub brokers for
        brokers = {}
        federates = self.extract_annotated_topology_nodes('helics/federate')

        for fed in federates:
            if not self.is_booting(fed.general.hostname):
                continue

            self.add_label(fed.general.hostname, 'group', 'helics')
            self.add_label(fed.general.hostname, 'helics', 'federate')

            configs = fed.annotations.get('helics/federate', [])

            for config in configs:
                broker = config.get('broker', '127.0.0.1')
                count  = config.get('fed-count', 1)

                total_fed_count += count

                if '|' in broker: # hostname|iface
                    broker_hostname, iface = broker.split('|', 1)
                    broker_ip = self.extract_node_interface_ip(broker_hostname, iface)

                    if not broker_ip:
                        logger.log('ERROR', f'broker not found in topology: {broker_hostname}')
                        sys.exit(1)
                else: # ip[:port]
                    broker_ip = broker

                if broker_ip == root_ip:
                    # not connecting to sub broker
                    continue

                if ':' not in broker_ip:
                    # default to port 24000 for sub broker
                    broker_ip += ':24000'

                hostname = self.extract_node_hostname_for_ip(broker_ip)

                if not hostname:
                    logger.log('ERROR', f'node not found for broker at {broker}')
                    sys.exit(1)

                if not self.is_booting(hostname):
                    logger.log('ERROR', f'broker node is marked do not boot: {hostname}')

                self.add_label(hostname, 'group', 'helics')
                self.add_label(hostname, 'helics', 'broker')

                entry = brokers.get(hostname, {broker_ip: 0})
                entry[broker] += count

                brokers[hostname] = entry

        log_dir = broker_md.get('log-dir', '/var/log')

        root_broker_config = {
            'subs':      0,
            'feds':      total_fed_count,
            'endpoint':  root_ip,
            'log-level': broker_md.get('log-level', 'summary'),
            'log-file':  os.path.join(log_dir, 'helics-root-broker.log'),
        }

        # per-host broker configs, initialized with root broker
        configs = {root_hostname: [root_broker_config]}

        for hostname, subs in brokers.items():
            # just in case hostname is root broker, which was initialized above
            broker_configs = configs.get(hostname, [])

            # individual sub brokers for host (there will usually just be one)
            for endpoint, feds in subs.items():
                root_broker_config['subs'] += 1

                broker_configs.append({
                    'feds':      feds,
                    'parent':    root_ip,
                    'endpoint':  endpoint,
                    'log-level': broker_md.get('log-level', 'summary'),
                    'log-file':  os.path.join(log_dir, 'helics-sub-broker.log'),
                })

            configs[hostname] = broker_configs

        templates = utils.abs_path(__file__, 'templates/')

        for hostname, broker_configs in configs.items():
            start_file = f'{self.helics_dir}/{hostname}-broker.sh'

            with open(start_file, 'w') as f:
                utils.mako_serve_template('broker.mako', templates, f, configs=broker_configs)

            dst = '/etc/phenix/startup/90-helics-broker.sh'
            self.add_inject(hostname=hostname, inject={'src': start_file, 'dst': dst})


def main():
    Helics()


if __name__ == '__main__':
    main()
