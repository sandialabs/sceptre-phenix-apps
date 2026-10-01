from pathlib import Path

from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger


class Protonuke(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.startup_dir: Path = Path(self.exp_dir) / "startup"

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        nukes = self.extract_all_nodes()

        for vm in nukes:
            hostname = utils.validate_hostname(vm.hostname)

            args = str(vm.metadata.args)
            if "\n" in args or "\r" in args:
                raise AppError(
                    f"protonuke args for host '{hostname}' must not contain newlines"
                )

            path = utils.safe_join(self.startup_dir, f"{hostname}-protonuke")

            if vm.topology.hardware.os_type.upper() == "WINDOWS":
                kwargs = {
                    "src": str(path),
                    "dst": "/phenix/startup/90-protonuke.ps1",
                }

                templates = utils.abs_path(__file__, "templates/")

                with path.open("w") as f:
                    utils.mako_serve_template(
                        "protonuke.ps1.mako",
                        templates,
                        f,
                        protonuke_args=args,
                    )
            else:
                kwargs = {
                    "src": str(path),
                    "dst": "/etc/default/protonuke",
                }

                with path.open("w") as f:
                    f.write(f"PROTONUKE_ARGS = {args}")

            self.add_inject(hostname=hostname, inject=kwargs)

        logger.info(f"Started user application: {self.name}")
