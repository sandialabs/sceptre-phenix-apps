import os, subprocess, sys, uuid

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils


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
        nodes = self.extract_node_names()
        vms   = self.metadata.get('vms', [])

        mm = self.mm_init()

        for vm in vms:
            if vm.hostname not in nodes:
                self.eprint(f'{vm.hostname} is not in the topology')
                continue

            commands = vm.get(stage, [])

            if len(commands) == 0:
                self.print(f'{vm.hostname} has no commands for stage {stage}')
                continue

            for cmd in commands:
                if cmd.type == 'exec':
                    validator = cmd.get('validator', None)
                    wait      = cmd.get('wait', False)

                    if validator:
                        wait = True # force waiting so validation can occur

                    self.print(f"executing command '{cmd.args}' in VM {vm.hostname}")

                    if wait:
                        results = utils.mm_exec_wait(mm, vm.hostname, cmd.args)

                        self.print(f"command '{results['cmd']}' executed in VM {vm.hostname} using cc")

                        if results['exitcode']:
                            self.eprint(f"command '{results['cmd']}' returned a non-zero exit code of '{results['exitcode']}'")
                            sys.exit(1)

                        self.print(f"results from '{results['cmd']}':")
                        self.print(results['stdout'])

                        if validator:
                            self.print(f"validating results from '{results['cmd']}'")

                            tempfile = f'/tmp/{str(uuid.uuid4())}.sh'

                            with open(tempfile, 'w') as tf:
                                tf.write(validator)

                            proc = subprocess.run(
                                ['bash', tempfile, vm.hostname], input=results['stdout'].encode(), capture_output=True,
                            )

                            os.remove(tempfile)

                            if proc.returncode != 0:
                                stderr = proc.stderr.decode()
                                if stderr:
                                    self.eprint(f'results validation failed: {stderr}')
                                else:
                                    self.eprint('results validation failed')

                                sys.exit(1)
                            else:
                                self.print('results are valid')
                    else:
                        mm.cc_filter(f'name={vm.hostname}')
                        mm.cc_exec(cmd.args)

                        last_cmd = utils.mm_last_command(mm)
                        self.print(f"command '{last_cmd['cmd']}' executed in VM {vm.hostname} using cc")
                elif cmd.type == 'background':
                    self.print(f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc")

                    mm.cc_filter(f'name={vm.hostname}')
                    mm.cc_background(cmd.args)

                    last_cmd = utils.mm_last_command(mm)
                    self.print(f"command '{last_cmd['cmd']}' backgrounded in VM {vm.hostname}")
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
                        self.eprint(f'too many files provided for send command for VM {vm.hostname}: {cmd.args}')
                        sys.exit(1)

                    if not os.path.isabs(src):
                        src = '/phenix/' + src

                    if not os.path.isabs(dst):
                        dst = '/phenix/' + dst

                    self.print(f"sending file '{src}' to VM {vm.hostname} at '{dst}' using cc")

                    try:
                        utils.mm_send(mm, vm.hostname, src, dst)
                        self.print(f"file '{src}' sent to VM {vm.hostname} at '{dst}'")
                    except Exception as ex:
                        self.eprint(f"error sending '{src}' to VM {vm.hostname}: {ex}")
                        sys.exit(1)
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
                        self.eprint(f'too many files provided for recv command for VM {vm.hostname}: {cmd.args}')
                        sys.exit(1)

                    self.print(f"receiving file '{src}' from VM {vm.hostname} to `{dst}` using cc")

                    try:
                        utils.mm_recv(mm, vm.hostname, src, dst)
                        self.print(f"file '{src}' received from VM {vm.hostname} to `{dst}`")
                    except Exception as ex:
                        self.eprint(f"error receiving '{src}' from VM {vm.hostname}: {ex}")
                        sys.exit(1)


def main():
    CC()


if __name__ == '__main__':
    main()
