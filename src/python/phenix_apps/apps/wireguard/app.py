from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Wireguard(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.startup_dir: str = f"{self.exp_dir}/startup"

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        templates = utils.abs_path(__file__, "templates/")

        guards = self.extract_all_nodes()

        for vm in guards:
            path = f"{self.startup_dir}/{vm.hostname}-wireguard.conf"

            kwargs = {
                "src": path,
                "dst": "/etc/wireguard/wg0.conf",
            }

            self.add_inject(hostname=vm.hostname, inject=kwargs)

            with open(path, "w") as f:
                utils.mako_serve_template(
                    "wireguard_config.mako", templates, f, wireguard=vm.metadata
                )

            if vm.metadata.get("boot", False):
                path = f"{self.startup_dir}/{vm.hostname}-wireguard-enable.sh"

                kwargs = {
                    "src": path,
                    "dst": "/etc/phenix/startup/wireguard-enable.sh",
                }

                self.add_inject(hostname=vm.hostname, inject=kwargs)

                with open(path, "w") as f:
                    utils.mako_serve_template(
                        "wireguard_enable.mako", templates, f, name="wg0"
                    )

        logger.info(f"Started user application: {self.name}")
