import os

import ipaddress as ipaddr

from phenix_apps.apps import AppBase
from phenix_apps.common import utils, settings
from phenix_apps.common.logger import logger

class Caldera(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.app_dir: str = f"{self.exp_dir}/caldera"
        os.makedirs(self.app_dir, exist_ok=True)

        self.files_dir: str = f"{settings.PHENIX_DIR}/images/{self.exp_name}/caldera"
        os.makedirs(self.files_dir, exist_ok=True)


    def configure(self):
        logger.info(f'Configuring user app: {self.name}')

        md = self.metadata

        for idx, server in enumerate(md.get('servers', [])):
            node = {
                'type': 'VirtualMachine',
                'general': {
                    'hostname' : server.get('hostname', f'caldera-{idx}'),
                    'vm_type'  : 'kvm'
                },
                'hardware': {
                    'os_type' : 'linux',
                    'vcpus'   : server.get('cpu', 2),
                    'memory'  : server.get('memory', 8192),
                    'drives'  : [
                        {'image': server.get('image', 'caldera.qc2')},
                    ]
                },
                'network': {
                    'interfaces': []
                }
            }

            for idx, iface in enumerate(server.interfaces):
                ip = ipaddr.ip_interface(iface.address)

                interface = {
                    'name'    : f'IF{idx}',
                    'type'    : 'ethernet',
                    'proto'   : 'static',
                    'address' : str(ip.ip),
                    'mask'    : ip.network.prefixlen,
                    'gateway' : iface.gateway,
                    'vlan'    : iface.vlan
                }

                node['network']['interfaces'].append(interface)

            self.add_node(node)

        logger.info(f'Configured user app: {self.name}')


    def pre_start(self):
        logger.info(f'Starting user application: {self.name}')

        templates = utils.abs_path(__file__, 'templates/')
        md = self.metadata

        for idx, server in enumerate(md.get('servers', [])):
            hostname = server.get('hostname', f'caldera-{idx}')

            node = self.extract_node(hostname)
            addr = node.network.interfaces[0].address

            for fact in server.get('facts', []):
                inject = {
                    'src': fact,
                    'dst': f'/opt/caldera/data/sources/{os.path.basename(fact)}',
                }

                self.add_inject(hostname, inject)

            for adversary in server.get('adversaries', []):
                inject = {
                    'src': adversary,
                    'dst': f'/opt/caldera/data/adversaries/{os.path.basename(adversary)}',
                }

                self.add_inject(hostname, inject)

            if server.get('config'):
                config_file = server.get('config')
            else:
                config_file = f'{self.app_dir}/{hostname}-config.yml'

                with open(config_file, 'w') as f:
                    utils.mako_serve_template('default_config.mako', templates, f)

            inject = {
                'src': config_file,
                'dst': f'/opt/caldera/conf/default.yml',
            }

            self.add_inject(hostname, inject)

            firefox_bookmark_config_file = f'{self.app_dir}/{hostname}-firefox-policies.json'

            with open(firefox_bookmark_config_file, 'w') as f:
                utils.mako_serve_template('firefox_bookmark.mako', templates, f, addr=addr)

            inject = {
                'src': firefox_bookmark_config_file,
                'dst': f'/etc/firefox/policies/policies.json',
            }

            self.add_inject(hostname, inject)

            firefox_autostart_config_file = f'{self.app_dir}/{hostname}-firefox-autostart.json'

            with open(firefox_autostart_config_file, 'w') as f:
                utils.mako_serve_template('firefox_autostart.mako', templates, f, addr=addr)

            inject = {
                'src': firefox_autostart_config_file,
                'dst': f'/root/.config/autostart/Caldera.desktop',
            }

            self.add_inject(hostname, inject)

        hosts = self.extract_all_nodes(False)

        for host in hosts:
            try:
                addr = ipaddr.ip_address(host.metadata.server)
            except:
                tokens = host.metadata.server.split(':')
                server = tokens[0]

                if len(tokens) == 1:
                    iface = 0
                else:
                    iface = int(tokens[1])

                node = self.extract_node(server)
                addr = node.network.interfaces[iface].address

            if host.topology.hardware.os_type == 'windows':
                agent_file = f'{self.app_dir}/{host.hostname}-sandcat-agent.ps1'

                with open(agent_file, 'w') as f:
                    utils.mako_serve_template('windows_agent.mako', templates, f, addr=addr)

                self.add_inject(hostname=host.hostname, inject={'src': agent_file, 'dst': '/phenix/startup/90-sandcat-agent.ps1'})
            elif host.topology.hardware.os_type == 'linux':
                agent_file = f'{self.app_dir}/{host.hostname}-sandcat-agent.sh'

                with open(agent_file, 'w') as f:
                    utils.mako_serve_template('linux_agent.mako', templates, f, addr=addr)

                self.add_inject(hostname=host.hostname, inject={'src': agent_file, 'dst': '/etc/phenix/startup/90-sandcat-agent.sh'})

        logger.info(f'Started user application: {self.name}')
