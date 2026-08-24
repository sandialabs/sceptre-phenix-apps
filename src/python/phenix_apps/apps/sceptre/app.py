"""The SCEPTRE phenix app: dispatch for the configure and pre-start stages."""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

from box import Box

from phenix_apps.apps import AppBase
from phenix_apps.apps.sceptre import hosts, validation
from phenix_apps.apps.sceptre.configure import ConfigureStage
from phenix_apps.apps.sceptre.prestart import PreStart
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Sceptre(AppBase):
    """Dispatches the configure and pre-start stages to the handler modules.

    Must stay in this module: AppBase resolves templates_dir from the class's
    __module__, so moving it breaks every render() call at runtime.
    """

    # Device types this app handles, in the order the inventory lists them.
    DEVICE_TYPES: Final[tuple[str, ...]] = (
        "provider",
        "fd-server",
        "fd-client",
        "fep",
        "opc",
        "scada-server",
        "hmi",
        "engineer-workstation",
        "historian",
        "elk",
    )

    # Hosts selected by label rather than by metadata.type.
    DEVICE_LABELS: Final[tuple[str, ...]] = ("helics-federate", "helics-broker", "elk")

    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        # Everything the app generates lands in one of these three. phenix may
        # run a later stage in a fresh process, hence exist_ok.
        self.startup_dir = Path(self.exp_dir) / "startup"
        self.sceptre_dir = Path(self.exp_dir) / "sceptre"
        self.elk_dir = Path(self.exp_dir) / "elk"

        for directory in (self.startup_dir, self.sceptre_dir, self.elk_dir):
            directory.mkdir(parents=True, exist_ok=True)

        # Override files that matched an injection, for _warn_unused_overrides.
        self._used_overrides: set[str] = set()

    def _log_inventory(self, stage: str) -> None:
        """Log what the app found in the scenario, by device type."""

        nodes = self.extract_all_nodes()
        counts = [
            f"{device_type}={len(found)}"
            for device_type in self.DEVICE_TYPES
            if (found := self.extract_nodes_type(device_type))
        ]
        counts += [
            f"{label}={len(found)}"
            for label in self.DEVICE_LABELS
            if (found := self.extract_nodes_label(label))
        ]
        logger.info(f"sceptre {stage}: {len(nodes)} hosts -- {' '.join(counts)}")

        untyped = [h.hostname for h in nodes if not h.metadata.get("type")]
        if untyped:
            logger.debug(
                "hosts with no metadata.type (label-selected only): "
                + ", ".join(sorted(untyped))
            )

    def _injection_count(self) -> int:
        return sum(
            len(node.get("injections", []) or [])
            for node in self.experiment.spec.topology.nodes
        )

    def _generated_file_count(self) -> int:
        return sum(1 for path in Path(self.exp_dir).rglob("*") if path.is_file())

    def _run_steps(
        self,
        steps: Iterable[tuple[str, Callable[[], None]]],
        measure: Callable[[], int],
        unit: str,
    ) -> None:
        """Run each handler, logging what it produced.

        Keeps the accounting here so the handlers carry no logging.
        """

        for label, run in steps:
            before = measure()
            run()
            produced = measure() - before
            if produced:
                plural = "" if produced == 1 else "s"
                logger.info(f"  {label:<22} +{produced} {unit}{plural}")
            else:
                logger.debug(f"  {label:<22} nothing to do")

    def find_override(self, filename: str) -> dict[str, str] | None:
        """Return an injection src for a hand-written override, if one exists.

        Named "<hostname>_<generated name>", e.g. "opc-1_opc.xml".
        """

        # Without assetDir in the scenario, asset_dir is None and this never
        # exists.
        override = Path(f"{self.asset_dir}") / "injects" / "override" / filename
        if override.exists():
            logger.info(f"Overriding '{filename}' with '{override}'")
            self._used_overrides.add(filename)
            return {"src": str(override)}
        return None

    def _warn_unused_overrides(self) -> None:
        """A file in override/ that matched no injection is probably a typo."""

        override_dir = Path(f"{self.asset_dir}") / "injects" / "override"
        if not override_dir.is_dir():
            return

        unused = sorted(
            f.name
            for f in override_dir.iterdir()
            if f.is_file() and f.name not in self._used_overrides
        )
        if unused:
            logger.warning(
                "override files that matched no injection (typo in the hostname "
                f"or filename?): {', '.join(unused)}"
            )

    def inject(
        self,
        hostname: str,
        src: str | Path,
        dst: str,
        description: str = "",
        permissions: str | None = None,
        override: str | None = None,
    ) -> None:
        """Attach one file injection to a host.

        override is the name under <assetDir>/injects/override/ minus the
        "<hostname>_" prefix; that file wins over src when it exists.
        """

        inject = (
            self.find_override(f"{hostname}_{override}") if override else None
        ) or {"src": str(src)}
        inject["dst"] = dst
        inject["description"] = description
        if permissions:
            inject["permissions"] = permissions

        self.add_inject(hostname=hostname, inject=inject)

    def host_dir(self, hostname: str) -> Path:
        """A host's output directory under sceptre/, created. Pre-start only."""

        path = Path(self.sceptre_dir) / hostname
        path.mkdir(parents=True, exist_ok=True)
        return path

    def render_sceptre_start(self, device: Box, **kwargs: Any) -> None:
        """Render a device's sceptre-start script. Unset kwargs come from the device."""

        kwargs.setdefault("name", device.hostname)
        kwargs.setdefault("os", hosts.os_type(device))
        kwargs.setdefault("ips", hosts.interfaces(device))
        kwargs.setdefault("metadata", dict(device.metadata))

        ext = ".ps1" if hosts.os_type(device) == "windows" else ".sh"

        startup_file = Path(self.startup_dir) / f"{device.hostname}-start{ext}"
        self.render("sceptre_start.mako", startup_file, **kwargs)
        utils.mark_executable(startup_file)

    def add_sceptre_startup_injects_windows(self, hostname: str) -> None:
        """The two Windows startup-scheduler injections: phenix's scheduler
        cannot run as the local user, which UI automation needs."""

        self.inject(
            hostname,
            f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
            "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
            "sceptre startup scheduler",
        )
        self.inject(
            hostname,
            f"{self.startup_dir}/sceptre-startup.ps1",
            "sceptre/sceptre-startup.ps1",
            "sceptre startup script",
        )

    def configure(self) -> None:
        """Declare every injection: what file goes where on each VM.

        The files themselves are generated in pre_start, so the paths do not
        exist yet.
        """

        validation.enforce(self)
        self._log_inventory("configure")

        started = self._injection_count()

        self._run_steps(
            ConfigureStage(self).steps(), self._injection_count, "injection"
        )
        self._warn_unused_overrides()

        logger.info(
            f"sceptre configure: {self._injection_count() - started} injections added"
        )

    def pre_start(self) -> None:
        """Generate the files configure() promised to inject.

        The call order lives in PreStart.steps(), where it is load-bearing.
        """

        # Re-checked: phenix may run stages in separate processes.
        validation.enforce(self)
        self._log_inventory("pre-start")

        # Rendered unconditionally: add_sceptre_startup_injects_windows()
        # injects both by path during configure, for any Windows host.
        scheduler_file = Path(self.startup_dir) / "sceptre-startup-scheduler.cmd"
        self.render("sceptre-startup-scheduler.mako", scheduler_file)
        scheduler_file.chmod(0o0777)

        startup_file = Path(self.startup_dir) / "sceptre-startup.ps1"
        self.render("sceptre-startup.mako", startup_file)
        startup_file.chmod(0o777)

        started = self._generated_file_count()

        self._run_steps(PreStart(self).steps(), self._generated_file_count, "file")

        logger.info(
            f"sceptre pre-start: {self._generated_file_count() - started} files "
            f"generated under {self.exp_dir}"
        )
