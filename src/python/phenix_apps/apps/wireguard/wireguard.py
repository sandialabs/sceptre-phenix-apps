from phenix_apps.apps   import AppBase
from phenix_apps.common import logger, utils


class Wireguard(AppBase):
    def __init__(self):
        AppBase.__init__(self, 'wireguard')

        self.startup_dir = f"{self.exp_dir}/startup"

        self.execute_stage()

        # We don't (currently) let the parent AppBase class handle this step
        # just in case app developers want to do any additional manipulation
        # after the appropriate stage function has completed.
        print(self.experiment.to_json())


    def pre_start(self):
        logger.log('INFO', f'Starting user application: {self.name}')

        templates = utils.abs_path(__file__, 'templates/')

        guards = self.extract_all_nodes()

        for vm in guards:
            path = f"{self.startup_dir}/{vm.hostname}-wireguard.conf"

            kwargs = {
                'src': path,
                'dst': '/etc/wireguard/wg0.conf',
            }

            self.add_inject(hostname=vm.hostname, inject=kwargs)

            with open(path, 'w') as f:
                utils.mako_serve_template(
                    'wireguard_config.mako', templates, f, wireguard=vm.metadata
                )

            if vm.metadata.get('boot', False):
                path = f"{self.startup_dir}/{vm.hostname}-wireguard-enable.sh"

                kwargs = {
                    'src': path,
                    'dst': '/etc/phenix/startup/wireguard-enable.sh',
                }

                self.add_inject(hostname=vm.hostname, inject=kwargs)

                with open(path, 'w') as f:
                    utils.mako_serve_template(
                        'wireguard_enable.mako', templates, f, name='wg0'
                    )

        logger.log('INFO', f'Started user application: {self.name}')


def main():
    Wireguard()


if __name__ == '__main__':
    main()
