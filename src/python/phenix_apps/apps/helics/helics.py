import os, sys

from phenix_apps.apps   import AppBase
from phenix_apps.common import logger, utils

#  apps:
#  - name: helics
#    metadata:
#      broker:
#        root: <ip:port>    # optional location of root broker (assumed to already be in topology)
#        log-level: summary # log level to apply to every broker created

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

        total_fed_count = 0

        # broker hosts --> {endpoint: <ip:port>, fed-count: <num>}
        brokers = {}
        federates = self.extract_annotated_topology_nodes('helics/federate')

        for fed in federates:
            configs = fed['annotations'].get('helics/federate', [])

            for config in configs:
                broker = config.get('broker', '127.0.0.1')
                count  = config.get('fed-count', 1)

                total_fed_count += count

                if ':' in broker:
                    ip, _ = broker.split(':', 1)
                else:
                    ip = broker

                hostname = self.extract_node_hostname_for_ip(ip)

                entry = brokers.get(hostname, {'endpoint': broker, 'fed-count': 0})
                entry['fed-count'] += count

                brokers[hostname] = entry

        if len(brokers) > 1:
            root_ip = self.metadata.get('broker', {}).get('root', '127.0.0.1')

            if '|' in root_ip:
                root_hostname, iface = root_ip.split('|', 1)
                root_ip = self.extract_node_interface_ip(root_hostname, iface)

                if not root_ip:
                    logger.log('ERROR', f'root broker not found in topology: {root_hostname}')
                    sys.exit(1)
            else:
                root_hostname = self.extract_node_hostname_for_ip(root_ip)

                if not root_hostname:
                    logger.log('ERROR', f'root broker IP not found in topology: {root_ip}')
                    sys.exit(1)

            # TODO: add root broker to topology if it doesn't already exist?

        templates = utils.abs_path(__file__, 'templates/')

        for hostname, config in brokers.items():
            start_file = f'{self.helics_dir}/{hostname}-broker.sh'

            cfg = {
                'feds': config['fed-count'],
                'log-level': self.metadata.get('broker', {}).get('log-level', 'summary'),
                'log-file': self.metadata.get('broker', {}).get('log-file', '/var/log/helics-broker.log'),
            }

            if len(brokers) > 1:
                if root_hostname != hostname:
                    cfg['parent'] = root_ip
                    cfg['endpoint'] = config['endpoint']
                else:
                    cfg['feds'] = total_fed_count
                    cfg['subs'] = len(brokers) - 1

            with open(start_file, 'w') as f:
                utils.mako_serve_template('broker.mako', templates, f, cfg=cfg)

            self.add_inject(hostname=hostname, inject={'src': start_file, 'dst': '/etc/phenix/startup/90-helics-broker.sh'})


def main():
    Helics()


if __name__ == '__main__':
    main()
