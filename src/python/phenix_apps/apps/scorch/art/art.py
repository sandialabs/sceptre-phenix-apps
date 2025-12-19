import os, subprocess, sys, uuid

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

from box import Box


class AtomicRedTeam(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'art')

        self.execute_stage()


    def start(self):
        logger.info(f'Starting user component: {self.name}')

        goart      = self.metadata.get('framework', None)
        technique  = self.metadata.get('technique', None)
        test_name  = self.metadata.get('testName',  None)
        test_index = self.metadata.get('testIndex', None)

        mm = self.mm_init()

        if not goart or not os.path.exists(goart):
            self.eprint('goart executable not found')
            sys.exit(1)

        if not technique:
            self.eprint('no technique configured')
            sys.exit(1)

        if test_name is None and test_index is None:
            self.eprint('no technique test configured')
            sys.exit(1)

        vms = self.metadata.get('vms', None)

        for vm in vms:
            self.print(f'copying {goart} to {vm.hostname}')

            utils.mm_send(mm, vm.hostname, goart, f'/tmp/{os.path.basename(goart)}')

            mm.cc_filter(f'name={vm.hostname}')
            mm.cc_exec(f'chmod +x /tmp/{os.path.basename(goart)}')

            args = ['-q', '-f', 'json', '-t', self.metadata.technique]

            out_file = f'/tmp/{str(uuid.uuid4())}.json'

            args.extend(['-o', out_file])

            if test_index is not None:
                args.extend(['-i', str(test_index)])
            elif test_name is not None:
                args.extend(['-n', test_name])
            else: # should never get here...
                self.eprint('no technique test configured')
                sys.exit(1)

            inputs = vm.get('inputs', {})
            for name, value in inputs.items():
                args.extend(['--input', f'{name}={value}'])

            env = self.metadata.get('env', {})
            for name, value in env.items():
                args.extend(['--env', f'{name}={value}'])

            env = vm.get('env', {})
            for name, value in env.items():
                args.extend(['--env', f'{name}={value}'])

            cmd = f"/tmp/{os.path.basename(goart)} {' '.join(args)}"

            self.print(f'executing {cmd} in {vm.hostname}')

            utils.mm_exec_wait(mm, vm.hostname, cmd)

            self.print(f'getting results file {out_file} from {vm.hostname}')

            results_file = os.path.join(self.base_dir, f'{vm.hostname}.json')

            try:
                utils.mm_recv(mm, vm.hostname, out_file, results_file)
            except Exception as ex:
                self.eprint(f'failed to get results file: {ex}')
                sys.exit(1)

            validator = self.metadata.get('validator', None)

            if validator:
                self.print(f'validating results from {vm.hostname}')

                tempfile = f'/tmp/{str(uuid.uuid4())}.sh'

                with open(tempfile, 'w') as tf:
                    tf.write(validator)

                results = Box.from_json(filename=results_file)

                proc = subprocess.run(
                    ['sh', tempfile, vm.hostname],
                    input=results.Executor.ExecutedCommand.results.encode(),
                    capture_output=True,
                )

                if proc.returncode != 0:
                    stderr = proc.stderr.decode()
                    if stderr:
                        self.eprint(f'results validation failed: {stderr}')
                    else:
                        self.eprint('results validation failed')

                    if self.metadata.get('abortOnError', False): os.exit(1)
                else:
                    self.print('results are valid')

                os.remove(tempfile)

        logger.info(f'Started user component: {self.name}')


def main():
    AtomicRedTeam()


if __name__ == '__main__':
    main()
