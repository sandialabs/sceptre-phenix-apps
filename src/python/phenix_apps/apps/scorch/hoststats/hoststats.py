import json
import os
import signal
import threading
import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger


class HostStats(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'hoststats')

        self.poll_period  = self.metadata.get('pollPeriod', 5)
        self.flush_period = self.metadata.get('flushPeriod', None)

        if self.flush_period is None or self.flush_period < self.poll_period:
            self.flush_period = self.poll_period

        self.resdata = []
        self.monitor = False

        self.execute_stage()


    def start(self):
        logger.info(f'Starting user component: {self.name}')

        self.monitor = True

        thread = threading.Thread(target=self.__run_monitor)
        thread.start()

        logger.info(f'Started user component: {self.name}')

        # wait for calling process to send SIGTERM
        signal.pause()
        self.monitor = False

        logger.info(f'Stopping user component: {self.name}')

        thread.join()
        self.__flush_buffer()

        logger.info(f'Stopped user component: {self.name}')


    def __run_monitor(self):
        count = 0

        while self.monitor:
            data = self.__get_resdata()

            if data:
                self.resdata.extend(data)

            if count % int(self.flush_period/self.poll_period) == 0:
                self.__flush_buffer()

            time.sleep(self.poll_period)
            count += 1


    def __flush_buffer(self):
        if not self.resdata:
            return

        output_file = os.path.join(self.base_dir, 'host_stats.jsonl')

        # write jsonl
        with open(output_file, 'a+') as f:
            for datum in self.resdata:
                json_record = json.dumps(datum)
                f.write(json_record + '\n')

        # clear buffer
        self.resdata = []


    def __get_resdata(self):
        resdata  = []
        host_vms = {}
        vm_info  = self.mm.vm_info()

        try:
            for host in vm_info:
                name_indx = host['Header'].index('name')
                host_vms[host['Host']] =  []

                for vm in host['Tabular']:
                    host_vms[host['Host']].append(vm[name_indx])
        except TypeError:
            pass

        host_info = self.mm.host()

        self.print(f"getting host data for {len(vm_info)} hosts")
        try:
            for host in host_info:
                host_dict = {}

                host_dict['compute_name'] = host['Data'].pop('Name')
                host_dict.update(host['Data'])

                loads = host_dict.pop('Load').split()

                host_dict['Load_1']  = float(loads[0])
                host_dict['Load_5']  = float(loads[1])
                host_dict['Load_15'] = float(loads[2])

                host_dict['timestamp'] = int(time.time()*1000)  # milliseconds
                host_dict['vm_list']   = sorted(host_vms.get(host_dict['compute_name'], []))

                resdata.append(host_dict)
        except TypeError:
            return []

        # print current data so users can see it in UI modal in real-time
        self.print(resdata)
        return resdata


def main():
    HostStats()


if __name__ == '__main__':
    main()
