import os, subprocess, sys, uuid

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils

from box import Box


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

            if len(commands) == 0:
                self.eprint(f'{vm.hostname} has no commands for stage {stage}')
                os.exit(1)

            for cmd in commands:
                if cmd.type == 'exec':
                    validator = cmd.get('validator', None)
                    wait      = cmd.get('wait', False)

                    if validator:
                        wait = True # force waiting so validation can occur

                    wait = cmd.get('wait', False)

                    self.print(f"executing command '{cmd.args}' in VM {vm.hostname} using cc")

                    if wait:
                        results = utils.mm_exec_wait(mm, vm.hostname, cmd.args)

                        if validator:
                            self.print(f'validating results from {vm.hostname}')

                            tempfile = f'/tmp/{str(uuid.uuid4())}.sh'

                            with open(tempfile, 'w') as tf:
                                tf.write(validator)

                            proc = subprocess.run(
                                ['sh', tempfile, vm.hostname], input=results, capture_output=True,
                            )

                            os.remove(tempfile)

                            if proc.returncode != 0:
                                stderr = proc.stderr.decode()
                                if stderr:
                                    self.eprint(f'results validation failed: {stderr}')
                                else:
                                    self.eprint('results validation failed')

                                os.exit(1)
                            else:
                                self.print('results are valid')
                    else:
                        mm.cc_filter(f'name={vm.hostname}')
                        mm.cc_exec(cmd.args)
                elif cmd.type == 'background':
                    self.print(f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc")

                    mm.cc_filter(f'name={vm.hostname}')
                    mm.cc_background(cmd.args)
                elif cmd.type == 'send':
                    args = cmd.args.split(':')
                    src  = None
                    dst  = None

                    if len(args) == 1:
                        src = dst = args[0]
                    elif len(args) == 2:
                        src = args[0]
                        dst = args[1]
                    else:
                        self.eprint(f'too many files provided for send command: {cmd.args}')
                        sys.exit(1)

                    if not os.path.isabs(src):
                        src = '/phenix/' + src

                    if not os.path.isabs(dst):
                        dst = '/phenix/' + dst

                    self.print(f"sending file '{src}' to VM {vm.hostname} at '{dst}' using cc")

                    utils.mm_send(mm, vm.hostname, src, dst)
                elif cmd.type == 'recv':
                    args = cmd.args.split(':')
                    src  = None
                    dst  = None

                    if len(args) == 1:
                        src = args[0]
                        dst = self.base_dir + '/' + os.path.basename(src)
                    elif len(args) == 2:
                        src = args[0]
                        dst = args[1]
                    else:
                        self.eprint(f'too many files provided for recv command: {cmd.args}')
                        sys.exit(1)

                    self.print(f"receiving file '{src}' from VM {vm.hostname} to `{dst}` using cc")

                    utils.mm_recv(mm, vm.hostname, src, dst)


def main():
    CC()


if __name__ == '__main__':
    main()
