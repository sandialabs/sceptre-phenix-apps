import os, subprocess, sys, uuid

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, settings, utils


class CC(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'cc')

        self.execute_stage()


    def configure(self):
        self.__run('configure')


    def start(self):
        self.__run('start')


    def stop(self):
        self.__run('stop')


    def cleanup(self):
        self.__run('cleanup')


    def __run(self, stage):
        vms = self.metadata.get('vms', [])

        mm = self.mm_init()

        for vm in vms:
            commands = vm.get(stage, [])

            for cmd in commands:
                if cmd.type == 'exec':
                    wait = cmd.get('wait', False)

                    self.print(f"executing command '{cmd.args}' in VM {vm.hostname} using cc")

                    if wait:
                        utils.mm_exec_wait(mm, vm.hostname, cmd.args)
                    else:
                        mm.cc_filter(f'name={vm.hostname}')
                        mm.cc_exec(cmd.args)
                elif cmd.type == 'background':
                    self.print(f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc")

                    mm.cc_filter(f'name={vm.hostname}')
                    mm.cc_background(cmd.args)
                elif cmd.type == 'send':
                    self.print(f"sending file '{cmd.args}' to VM {vm.hostname} using cc")

                    mm.cc_filter(f'name={vm.hostname}')
                    mm.cc_send(cmd.args)
                elif cmd.type == 'recv':
                    self.print(f"receiving file '{cmd.args}' from VM {vm.hostname} using cc")

                    mm.cc_filter(f'name={vm.hostname}')
                    mm.cc_recv(cmd.args)


def main():
    CC()


if __name__ == '__main__':
    main()
