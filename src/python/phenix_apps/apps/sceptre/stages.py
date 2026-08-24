"""What both lifecycle stages need from the app, and what pre-start shares.

`Stage` is the half of `Sceptre` a handler actually uses -- host lookups, the
output directories, injecting and rendering. `PreStartState` adds the data the
pre-start handlers hand each other; the clusters in `field_devices.py` and
`scada.py` inherit it, so `self.fd_server_configs` resolves in their own MRO
rather than arriving from nowhere.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from box import Box

if TYPE_CHECKING:
    from collections.abc import Callable

    from phenix_apps.apps.sceptre.app import Sceptre
    from phenix_apps.apps.sceptre.configs.configs import OpcConfig

Steps = tuple[tuple[str, "Callable[[], None]"], ...]


class Stage:
    """One lifecycle stage, with the app it runs against."""

    def __init__(self, app: "Sceptre") -> None:
        self.app = app

    def steps(self) -> Steps:
        """Each handler with the label the run log gives it, in call order."""

        raise NotImplementedError

    # -- the app, in the terms handlers use it ----------------------------

    @property
    def sceptre_dir(self) -> Path:
        return Path(self.app.sceptre_dir)

    @property
    def startup_dir(self) -> Path:
        return Path(self.app.startup_dir)

    @property
    def elk_dir(self) -> Path:
        return Path(self.app.elk_dir)

    def hosts(self, device_type: str) -> list[Box]:
        """Hosts with this metadata.type."""

        return self.app.extract_nodes_type(device_type)

    def labelled(self, label: str) -> list[Box]:
        """Hosts carrying this metadata label."""

        return self.app.extract_nodes_label(label)

    def host_dir(self, hostname: str) -> Path:
        """A host's output directory, created."""

        return self.app.host_dir(hostname)

    def inject(
        self,
        hostname: str,
        src: str | Path,
        dst: str,
        description: str = "",
        permissions: str | None = None,
        override: str | None = None,
    ) -> None:
        """Declare one file injection. See Sceptre.inject."""

        self.app.inject(hostname, src, dst, description, permissions, override)

    def render(self, template: str, path: str | Path, **kwargs: Any) -> None:
        """Render a Mako template to a file."""

        self.app.render(template, path, **kwargs)


class PreStartState(Stage):
    """The data pre-start handlers hand each other, in call order.

    Each handler's docstring names what it reads and writes, which is what makes
    the order in PreStart.steps() reviewable.
    """

    def __init__(self, app: "Sceptre") -> None:
        super().__init__(app)

        # Providers, keyed by hostname.
        self.provider_map: dict[str, Box] = {}
        self.provider_hosts: list[Box] = []

        # Only a PowerWorld provider sets a path to write objects to.
        self.objects_file_path: str | None = None
        self.hil_object_list: list[str] = []
        self.power_object_list: list[str] = []

        # Field device configs, keyed by hostname. feps() pops adopted RTUs out.
        self.fd_server_configs: dict[str, Any] = {}
        self.fdlist: dict[str, dict[str, int]] = {}

        # Never populated by the app today.
        self.reg_config: dict[str, Any] = {}

        self.scada_hosts: list[Box] = []
        self.historian_hosts: list[Box] = []
        self.scada_ips: list[str] = []
        self.historian_ips: list[str] = []

        self.opc_configs: dict[str, OpcConfig] = {}
        self.opc_bak_configs: dict[str, OpcConfig] = {}
