import os, time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils


class TrafficGen(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'trafficgen')

        self.execute_stage()


    def configure(self):
        logger.log('INFO', f'Configuring user component: {self.name}')

        scripts = self.metadata.get('scripts', {})
        targets = self.metadata.get('targets', None)

        mm = self.mm_init()

        for target in targets:
            hostname = target.get('hostname', 'traffic-server')
            script   = scripts['trafficServer']

            self.print(f'copying {os.path.basename(script)} to {hostname}')

            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/trafficgen-test/scripts/traffic-server.py, then
            # it will be copied to /traffic-server.py in the VM.
            utils.mm_send(mm, hostname, script, os.path.basename(script))

            background = target.get('backgroundClient', None)

            if background:
                hostname = background.get('hostname', 'background-gen')
                script   = scripts['backgroundGen']

                self.print(f'copying {os.path.basename(script)} to {hostname}')

                utils.mm_send(mm, hostname, script, os.path.basename(script))
            else:
                self.print('no background client configured for target {hostname}')

            malware = target.get('malwareClient', None)

            if malware:
                hostname = malware.get('hostname', 'malware-gen')
                script   = scripts['malwareGen']

                self.print(f'copying {os.path.basename(script)} to {hostname}')

                utils.mm_send(mm, hostname, script, os.path.basename(script))
            else:
                self.print('no malware client configured for target {hostname}')

        logger.log('INFO', f'Configured user component: {self.name}')


    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        scripts = self.metadata.get('scripts', {})
        targets = self.metadata.get('targets', None)

        mm = self.mm_init()

        for target in targets:
            target_host   = target.get('hostname', 'traffic-server')
            target_iface  = target.get('interface', 'IF0')
            target_script = scripts['trafficServer']
            target_ip     = self.extract_node_ip(target_host, target_iface)
            duration      = target.get('duration', 5)

            background = target.get('backgroundClient', None)

            if background:
                hostname = background.get('hostname', 'background-gen')
                rate     = background.get('rate', 10000)
                prob     = background.get('probability', .01)
                script   = scripts['backgroundGen']

                self.print(f'running {os.path.basename(target_script)} on {target_host}')

                mm.cc_filter(f'name={target_host}')
                mm.cc_background(f'python3 /{os.path.basename(target_script)}')

                self.print(f'running {os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_background(
                    f'python3 /{os.path.basename(script)} --ip {target_ip} '
                    f'--rate {rate} --duration {duration} --probability {prob}'
                )
            else:
                self.print('no background client configured for target {target_host}')

            malware = target.get('malwareClient', None)

            if malware:
                hostname = malware.get('hostname', 'malware-gen')
                rate     = background.get('rate', 20)
                prob     = background.get('probability', 1.25)
                script   = scripts['malwareGen']

                self.print(f'running {os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_background(
                    f'python3 /{os.path.basename(script)} --ip {target_ip} '
                    f'--rate {rate} --duration {duration} --probability {prob}'
                )
            else:
                self.print('no malware client configured for target {target_host}')

            self.print(f'pausing for {int(duration) + 5}s while traffic is generated for {target_host}')

            time.sleep(int(duration) + 5)

        logger.log('INFO', f'Started user component: {self.name}')


    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')

        scripts = self.metadata.get('scripts', {})
        targets = self.metadata.get('targets', None)

        mm = self.mm_init()

        for target in targets:
            target_host   = target.get('hostname', 'traffic-server')
            target_script = scripts['trafficServer']

            background = target.get('backgroundClient', None)

            if background:
                hostname = background.get('hostname', 'background-gen')
                script   = scripts['backgroundGen']

                self.print(f'killing {os.path.basename(target_script)} on {target_host}')

                mm.cc_filter(f'name={target_host}')
                mm.cc_exec(f'pkill -f {os.path.basename(target_script)}')

                self.print(f'killing {os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_exec(f'pkill -f {os.path.basename(script)}')
            else:
                self.print('no background client configured for target {target_host}')

            malware = target.get('malwareClient', None)

            if malware:
                hostname = malware.get('hostname', 'malware-gen')
                script   = scripts['malwareGen']

                self.print(f'killing {os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_exec(f'pkill -f {os.path.basename(script)}')
            else:
                self.print('no malware client configured for target {target_host}')

        logger.log('INFO', f'Stopped user component: {self.name}')


    def cleanup(self):
        logger.log('INFO', f'Cleaning up user component: {self.name}')

        scripts = self.metadata.get('scripts', {})
        targets = self.metadata.get('targets', None)

        mm = self.mm_init()

        for target in targets:
            target_host   = target.get('hostname', 'traffic-server')
            target_script = scripts['trafficServer']

            background = target.get('backgroundClient', None)

            if background:
                hostname = background.get('hostname', 'background-gen')
                script   = scripts['backgroundGen']

                self.print(f'deleting /{os.path.basename(target_script)} on {target_host}')

                mm.cc_filter(f'name={target_host}')
                mm.cc_exec(f'rm /{os.path.basename(target_script)}')

                self.print(f'deleting /{os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_exec(f'rm /{os.path.basename(script)}')
            else:
                self.print('no background client configured for target {target_host}')

            malware = target.get('malwareClient', None)

            if malware:
                hostname = malware.get('hostname', 'malware-gen')
                script   = scripts['malwareGen']

                self.print(f'deleting /{os.path.basename(script)} on {hostname}')

                mm.cc_filter(f'name={hostname}')
                mm.cc_exec(f'rm /{os.path.basename(script)}')
            else:
                self.print('no malware client configured for target {target_host}')

        logger.log('INFO', f'Cleaned up user component: {self.name}')


def main():
    TrafficGen()


if __name__ == '__main__':
    main()
