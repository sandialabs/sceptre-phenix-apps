import json
import sys
import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils


class VMStats(ComponentBase):
    """
    Collects resource utilization statistics from VMs in the experiment, using the `vmstats` command.
    """

    def __init__(self):
        ComponentBase.__init__(self, 'vmstats')
        self.execute_stage()

    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        freq = self.metadata.get('pollPeriod', 1)
        vms = self.__vm_list()

        for vm in vms:
            self.mm.vm_tag(vm, "vmstat", "1")

        self.mm.clear_cc_prefix()
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_background(f"bash -c 'vmstat -n -t {freq} >> /vmstat.out'")
        self.mm.clear_cc_filter()

        logger.log('INFO', f'Started user component: {self.name}')

    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')

        vms = self.__vm_list()

        self.print("killing vmstat processes")
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_exec_once("pkill vmstat")
        self.mm.clear_cc_filter()

        time.sleep(5.0)

        for i, vm in enumerate(vms):
            self.print(f"transferring /vmstat.out from {vm} ({i+1} of {len(vms)})")
            try:
                utils.mm_recv(self.mm, vm, '/vmstat.out', f'{self.base_dir}/{vm}.out')
            except ValueError as ex:
                self.eprint(f"Failed to get vmstat.out from {vm}: {ex}")
                sys.exit(1)

        self.print("deleting vmstat.out from VMs")
        self.mm.cc_filter("vmstat=1 os=linux")
        self.mm.cc_exec_once("rm /vmstat.out")
        self.mm.clear_cc_filter()

        stats = []

        self.print("reading vmstat.out files")
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

        stats_path = f'{self.base_dir}/vm_stats.jsonl'
        self.print(f"writing consolidated vmstats to {stats_path}")
        with open(stats_path, 'a+') as f:
            for datum in stats:
                json_record = json.dumps(datum)
                f.write(json_record + '\n')

        logger.log('INFO', f'Stopped user component: {self.name}')

    def __vm_list(self) -> list:
        vms = self.metadata.get('vms', None)
        compatible_os = ["linux", "centos", "rhel"]

        if vms:  # if specific vms are configured in metadata
            expanded = []

            for vm in vms:
                expanded = utils.expand_shorthand(vm)

            vms = [e for sub in expanded for e in sub]
        else:  # default to all linux VMs
            vms = []
            for vm in self.extract_node_names():
                node = self.extract_node(vm)

                if node.get("hardware", {}).get("os_type", "") in compatible_os:
                    vms.append(vm)
                else:
                    self.print(f"Skipping VM {vm} with incompatible os_type '{node.get('hardware', {}).get('os_type', '')}' (must be one of {compatible_os})")

        return vms


def main():
    VMStats()


if __name__ == '__main__':
    main()
