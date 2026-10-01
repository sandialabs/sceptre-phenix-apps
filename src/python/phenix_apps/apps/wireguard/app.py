from pathlib import Path

from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger


def _validate_single_line(hostname: str, field: str, value) -> None:
    """Reject config values that could inject extra lines into wg0.conf."""

    if "\n" in str(value) or "\r" in str(value):
        raise AppError(
            f"wireguard metadata field '{field}' for host '{hostname}' "
            "must not contain newlines"
        )


class Wireguard(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.startup_dir: Path = Path(self.exp_dir) / "startup"

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        templates = utils.abs_path(__file__, "templates/")

        guards = self.extract_all_nodes()

        for vm in guards:
            hostname = utils.validate_hostname(vm.hostname)

            for key, value in vm.metadata.get("interface", {}).items():
                _validate_single_line(hostname, f"interface.{key}", value)

            for idx, peer in enumerate(vm.metadata.get("peers", [])):
                for key, value in peer.items():
                    _validate_single_line(hostname, f"peers[{idx}].{key}", value)

            path = utils.safe_join(self.startup_dir, f"{hostname}-wireguard.conf")

            kwargs = {
                "src": str(path),
                "dst": "/etc/wireguard/wg0.conf",
            }

            self.add_inject(hostname=hostname, inject=kwargs)

            with path.open("w") as f:
                utils.mako_serve_template(
                    "wireguard_config.mako", templates, f, wireguard=vm.metadata
                )

            # the config contains the interface's private key
            path.chmod(0o600)

            if vm.metadata.get("boot", False):
                path = utils.safe_join(
                    self.startup_dir, f"{hostname}-wireguard-enable.sh"
                )

                kwargs = {
                    "src": str(path),
                    "dst": "/etc/phenix/startup/wireguard-enable.sh",
                }

                self.add_inject(hostname=hostname, inject=kwargs)

                with path.open("w") as f:
                    utils.mako_serve_template(
                        "wireguard_enable.mako", templates, f, name="wg0"
                    )

        logger.info(f"Started user application: {self.name}")
