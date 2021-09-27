import json

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils


class VMStats(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'vmstats')

        self.execute_stage()


    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        freq = self.metadata.get('pollPeriod', 1)
        vms  = self.__vm_list()

        mm = self.mm_init()

        for vm in vms:
            mm.cc_filter(f'name={vm}')
            mm.cc_background(f"bash -c 'vmstat -n -t {freq} >> /vmstat.out'")

        logger.log('INFO', f'Started user component: {self.name}')


    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')

        vms = self.__vm_list()

        mm = self.mm_init()

        for vm in vms:
            mm.cc_filter(f'name={vm}')
            mm.cc_exec('pkill vmstat')
            utils.mm_recv(mm, vm, '/vmstat.out', f'{self.base_dir}/{vm}.out')
            mm.cc_exec('rm /vmstat.out')

        stats = []

        for vm in vms:
            with open(f'{self.base_dir}/{vm}.out', 'r') as f:
                lines = f.readlines()

                for i, line in enumerate(lines):
                    if i in (0,1):
                        continue

                    items = []

                    for item in line.split():
                        try:
                            items.append(int(item))
                        except ValueError:
                            items.append(item)

                    items[-2] = f'{items[-2]} {items[-1]}'
                    del items[-1]

                    stat = dict(zip(lines[1].split(), items))
                    stat['vm_name'] = vm

                    stats.append(stat)

        with open(f'{self.base_dir}/vm_stats.jsonl', 'a+') as f:
            for datum in stats:
                json_record = json.dumps(datum)
                f.write(json_record + '\n')

        logger.log('INFO', f'Stopped user component: {self.name}')


    def __vm_list(self):
        vms  = self.metadata.get('vms', None)

        if vms:
            expanded = []

            for vm in vms:
                expanded = utils.expand_shorthand(vm)

            vms = [e for sub in expanded for e in sub]
        else:
            vms = self.extract_node_names()

        return vms


def main():
    VMStats()


if __name__ == '__main__':
    main()
