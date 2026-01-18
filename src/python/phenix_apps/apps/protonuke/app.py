from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Protonuke(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.startup_dir: str = f"{self.exp_dir}/startup"

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        nukes = self.extract_all_nodes()

        for vm in nukes:
            path = f"{self.startup_dir}/{vm.hostname}-protonuke"

            if vm.topology.hardware.os_type.upper() == "WINDOWS":
                kwargs = {
                    "src": path,
                    "dst": "/phenix/startup/90-protonuke.ps1",
                }

                templates = utils.abs_path(__file__, "templates/")

                with open(path, "w") as f:
                    utils.mako_serve_template(
                        "protonuke.ps1.mako",
                        templates,
                        f,
                        protonuke_args=vm.metadata.args,
                    )
            else:
                kwargs = {
                    "src": path,
                    "dst": "/etc/default/protonuke",
                }

                with open(path, "w") as f:
                    f.write(f"PROTONUKE_ARGS = {vm.metadata.args}")

            self.add_inject(hostname=vm.hostname, inject=kwargs)

        logger.info(f"Started user application: {self.name}")
