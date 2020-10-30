from phenix_apps.apps   import AppBase
from phenix_apps.common import logger

class Protonuke(AppBase):
    def __init__(self):
        AppBase.__init__(self, 'protonuke')

        self.startup_dir = f"{self.exp_dir}/startup"

        self.execute_stage()

        # We don't (currently) let the parent AppBase class handle this step
        # just in case app developers want to do any additional manipulation
        # after the appropriate stage function has completed.
        print(self.experiment.to_json())


    def pre_start(self):
        logger.log('INFO', f'Starting user application: {self.name}')

        nukes = self.extract_all_nodes()

        for vm in nukes:
            path = f'{self.startup_dir}/{vm.hostname}-protonuke'

            kwargs = {
                'src' : path,
                'dst' : '/etc/default/protonuke',
            }

            self.add_inject(hostname=vm.hostname, inject=kwargs)

            with open(path, 'w') as f:
                f.write('PROTONUKE_ARGS = {}'.format(vm.metadata.args))

        logger.log('INFO', f'Started user application: {self.name}')


def main():
    Protonuke()


if __name__ == '__main__':
    main()
