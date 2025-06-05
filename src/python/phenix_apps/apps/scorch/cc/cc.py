import os
import subprocess
import sys
import uuid

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

    def __run(self, stage: str) -> None:
        nodes = self.extract_node_names()
        vms = self.metadata.get('vms', [])
        commands = self.metadata.get(stage, [])

        for cmd in commands:
            if cmd.type == 'reset':
                self.__reset_cc()
            else:
                self.eprint(f"Unknown command type '{cmd.type}' for stage '{stage}'")
                sys.exit(1)

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
                    once      = cmd.get('once', True)

                    if validator:
                        wait = True # force waiting so validation can occur

                    self.print(f"executing command '{cmd.args}' in VM {vm.hostname}")

                    script = self.__send_cmd_as_file(vm.hostname, cmd.args)

                    if wait:
                        results = utils.mm_exec_wait(self.mm, vm.hostname, script, once=once)

                        self.print(f"command '{cmd.args}' executed in VM {vm.hostname} using cc")

                        node = self.extract_node(vm.hostname)

                        # HACK: If Windows, use presence of stderr to determine
                        # success/failure instead of exit code. Ugh...
                        if node.hardware.os_type.lower() == "windows":
                            if results['stderr']:
                                self.eprint(f"command '{cmd.args}' resulted in output to STDERR (assuming failure)")
                                self.print(f"STDERR Output: {results['stderr']}")

                                sys.exit(1)
                        elif results['exitcode']:
                            self.eprint(f"command '{cmd.args}' returned a non-zero exit code of '{results['exitcode']}'")

                            if results['stderr']:
                                self.print(f"STDERR Output: {results['stderr']}")

                            sys.exit(1)

                        if results['stdout']:
                            self.print(f"STDOUT Output: {results['stdout']}")

                        if validator:
                            self.print(f"validating results from '{cmd.args}'")

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
                        self.mm.cc_filter(f'name={vm.hostname}')

                        if once:
                            self.mm.cc_exec_once(script)
                        else:
                            self.mm.cc_exec(script)

                        self.print(f"command '{cmd.args}' executed in VM {vm.hostname} using cc")
                elif cmd.type == 'background':
                    once = cmd.get('once', True)

                    self.print(f"backgrounding command '{cmd.args}' in VM {vm.hostname} using cc")

                    script = self.__send_cmd_as_file(vm.hostname, cmd.args)

                    self.mm.cc_filter(f'name={vm.hostname}')

                    if once:
                        self.mm.cc_background_once(script)
                    else:
                        self.mm.cc_background(script)

                    self.mm.clear_cc_filter()
                    self.print(f"command '{cmd.args}' backgrounded in VM {vm.hostname}")
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
                        utils.mm_send(self.mm, vm.hostname, src, dst)
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
                        utils.mm_recv(self.mm, vm.hostname, src, dst)
                        self.print(f"file '{src}' received from VM {vm.hostname} to `{dst}`")
                    except Exception as ex:
                        self.eprint(f"error receiving '{src}' from VM {vm.hostname}: {ex}")
                        sys.exit(1)
                elif cmd.type == 'reset':
                    self.__reset_cc()
                else:
                    self.eprint(f"Unknown command type '{cmd.type}' for VM '{vm.hostname}' and stage '{stage}'")
                    sys.exit(1)

    def __send_cmd_as_file(self, hostname, cmd):
        cmd_file = f'run-{self.extract_run_name()}_{str(uuid.uuid4())}'
        node     = self.extract_node(hostname)

        if node.hardware.os_type.lower() == "windows":
            cmd_file += '.ps1'
        else:
            cmd_file += '.sh'

        cmd_src = os.path.join(self.root_dir, self.exp_name, cmd_file)
        cmd_dst = os.path.join('/tmp/miniccc/files', self.exp_name, cmd_file)

        with open(cmd_src, 'w') as f:
            f.write(cmd)

        self.mm.cc_filter(f'name={hostname}')
        self.mm.cc_send(cmd_src)

        # wait for file to be sent via cc
        last_cmd = utils.mm_last_command(self.mm)
        utils.mm_wait_for_cmd(self.mm, last_cmd['id'])
        self.mm.clear_cc_filter()

        os.remove(cmd_src)

        if node.hardware.os_type.lower() == "windows":
            return f'powershell.exe -ExecutionPolicy Bypass -File {cmd_dst}'
        else:
            return f'bash {cmd_dst}'

    def __reset_cc(self):
        self.print("deleting miniccc commands and responses")
        self.mm.clear_cc_filter()
        self.mm.cc_delete_command("all")
        self.mm.cc_delete_response("all")
        self.mm.clear_cc_commands()
        self.mm.clear_cc_responses()

        # ensure miniccc_responses directory is empty
        miniccc_dir = utils.mm_get_cc_path(self.mm)
        if miniccc_dir and any(p.exists() for p in miniccc_dir.iterdir()):
            self.eprint(f"WARNING: miniccc responses still exist in '{miniccc_dir}' even after clearing! number remaining: {len(list(miniccc_dir.iterdir()))}")
            # sys.exit(1)


def main():
    CC()


if __name__ == '__main__':
    main()
