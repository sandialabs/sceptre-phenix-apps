"""Everything simulator-specific, one section per simulator.

Each simulator has up to three hooks, colocated here so its whole story reads
in one place: the metadata fields validation requires, the injections the
configure stage declares, and the config.ini kwargs pre-start renders with.
The INJECTIONS table and family sets at the bottom are the dispatch; a
simulator can sit in more than one family (PowerWorldHelics is both a
PowerWorld and a Helics).
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict

from box import Box

from phenix_apps.apps.sceptre.metadata import Simulator

if TYPE_CHECKING:
    from phenix_apps.apps.sceptre.configure import ConfigureStage
    from phenix_apps.apps.sceptre.prestart import PreStart

# Where a Linux provider reads its config; PowerWorld runs on Windows and takes
# the relative path instead.
NIX_CONFIG: Final[str] = "/etc/sceptre/config.ini"


class ProviderConfig(TypedDict, total=False):
    """Every key provider_config.mako accepts; each simulator fills a subset.

    The template renders only the keys present, so a typo'd key silently
    disappears -- this vocabulary is what makes one visible to a type checker.
    """

    solver: str
    debug: str
    server_endpoint: str
    publish_endpoint: str
    case_file: str
    oneline_file: str
    pwds_endpoint: str
    config_helics: str
    config_file: str


# Provider metadata each simulator dereferences directly; validation enforces
# these pre-flight.
REQUIRED_METADATA: Final[dict[Simulator, tuple[str, ...]]] = {
    Simulator.POWER_WORLD: ("case", "oneline"),
    Simulator.POWER_WORLD_HELICS: ("case", "oneline"),
    Simulator.PYPOWER: ("case",),
    Simulator.SIMULINK: ("solver", "publish_points"),
    Simulator.GENERIC_PYTHON: ("simulation_file",),
}


# -------------------------------------------- PowerWorld / PowerWorldHelics


def power_world_injections(
    stage: "ConfigureStage", host: str, vm_directory: Path, provider: Box
) -> None:
    stage.inject(
        host,
        vm_directory / "config.ini",
        "sceptre/config.ini",
        "PowerWorld config",
        override="config.ini",
    )
    stage.inject(
        host,
        vm_directory / "objects.txt",
        "sceptre/objects.txt",
        "PowerWorld objects",
        override="objects.txt",
    )
    stage.inject(
        host,
        provider.metadata.case,
        "sceptre/case.PWB",
        "PowerWorld binary file",
    )
    stage.inject(
        host,
        provider.metadata.oneline,
        "sceptre/oneline.pwd",
        "PowerWorld display file",
    )


def power_world_kwargs(
    stage: "PreStart", provider: Box, provider_directory: Path
) -> ProviderConfig:
    """Shared by the whole POWER_WORLD_FAMILY, PowerWorldDynamics included."""

    stage.objects_file_path = str(provider_directory / "objects.txt")
    stage.hil_object_list = provider.metadata.get("hil_tags", [])
    return {"case_file": "case.PWB", "oneline_file": "oneline.pwd"}


# --------------------------------------------------------- PowerWorldDynamics


def power_world_dynamics_injections(
    stage: "ConfigureStage", host: str, vm_directory: Path, _provider: Box
) -> None:
    stage.inject(
        host,
        vm_directory / "config.ini",
        NIX_CONFIG,
        "PowerWorldDynamics config",
        override="config.ini",
    )
    stage.inject(
        host,
        vm_directory / "objects.txt",
        "/etc/sceptre/objects.txt",
        "PowerWorldDynamics objects",
        override="objects.txt",
    )


def power_world_dynamics_kwargs(provider: Box) -> ProviderConfig:
    return {"pwds_endpoint": provider.metadata.get("pwds_endpoint", "127.0.0.1")}


# ------------------------------------------------------------------ Simulink
# No config.ini kwargs: bennu launches the solver binary directly.


def simulink_injections(
    stage: "ConfigureStage", host: str, _vm_directory: Path, provider: Box
) -> None:
    stage.inject(
        host,
        provider.metadata.solver,
        "/etc/sceptre/simulinksolver",
        "Simulink solver binary",
        permissions="0777",
    )
    stage.inject(
        host,
        provider.metadata.publish_points,
        "/etc/sceptre/publishPoints.txt",
        "Simulink solver publish points",
        permissions="0664",
    )

    # Ground truth: an unmodified copy of the same simulator, to compare a
    # disruption against. Unverified since June 2023.
    if provider.metadata.get("gt"):
        stage.inject(
            host,
            provider.metadata.gt,
            "/etc/sceptre/simulinkgt",
            "Simulink solver ground truth binary",
            permissions="0777",
        )
        stage.inject(
            host,
            provider.metadata.gt_template,
            "/etc/sceptre/main.tmpl",
            "Simulink solver ground truth web template",
            permissions="0664",
        )


# ------------------------------------------------------------------- PyPower


def pypower_injections(
    stage: "ConfigureStage", host: str, vm_directory: Path, provider: Box
) -> None:
    stage.inject(
        host,
        vm_directory / "config.ini",
        NIX_CONFIG,
        "PyPower config",
        override="config.ini",
    )
    stage.inject(
        host,
        provider.metadata.case,
        f"/etc/sceptre/{Path(provider.metadata.case).name}",
        "PyPower case file",
    )


def pypower_kwargs(provider: Box) -> ProviderConfig:
    return {"case_file": Path(provider.metadata.case).name}


# ------------------------------------------------------------- GenericPython


def generic_python_injections(
    stage: "ConfigureStage", host: str, vm_directory: Path, provider: Box
) -> None:
    stage.inject(
        host,
        vm_directory / "config.ini",
        NIX_CONFIG,
        "Python provider config",
        override="config.ini",
    )
    stage.inject(
        host,
        provider.metadata.simulation_file,
        "/etc/sceptre/simulation.py",
        "Python simulation file",
    )


# -------------------------------------------------- Helics (and *Helics)


def helics_kwargs(is_linux: bool) -> ProviderConfig:
    path = "/etc/sceptre/helics.json" if is_linux else "C:/sceptre/helics.json"
    return {"config_helics": path}


# ------------------------------------------------------ RTDS / OPALRT / Siren
# YAML-configured: pre-start writes <sim>_config.yaml from the provider's own
# metadata, and configure injects it. metadata.config_file overrides it by
# hand; experiment metadata is then *not* added to that file.


def yaml_config_injections(
    stage: "ConfigureStage",
    host: str,
    vm_directory: Path,
    provider: Box,
    simulator: Simulator,
) -> None:
    if provider.metadata.get("config_file"):
        return

    name = f"{simulator.lower()}_config.yaml"
    stage.inject(
        host,
        vm_directory / name,
        f"/etc/sceptre/{name}",
        "YAML configuration file for Provider",
    )


def yaml_config_kwargs(
    stage: "PreStart",
    provider: Box,
    simulator: Simulator,
    provider_directory: Path,
    ipv4_address: str,
) -> ProviderConfig:
    """Write the YAML config and return the path config.ini names."""

    if provider.metadata.get("config_file"):
        return {"config_file": provider.metadata.config_file}

    if not provider.metadata.get("data_dir"):
        provider.metadata.data_dir = f"/root/{simulator.lower()}/"

    provider.metadata.sceptre_topology = (
        stage.app.experiment.metadata.annotations.topology
    )
    provider.metadata.sceptre_scenario = (
        stage.app.experiment.metadata.annotations.scenario
    )
    provider.metadata.sceptre_experiment = stage.app.exp_name
    provider.metadata.provider_hostname = provider.hostname
    provider.metadata.provider_ip = ipv4_address

    name = f"{simulator.lower()}_config.yaml"
    provider.metadata.to_yaml(filename=provider_directory / name)
    # Goes into the INI file.
    return {"config_file": f"/etc/sceptre/{name}"}


# ------------------------------------------------------------------- default


def default_injections(
    stage: "ConfigureStage", host: str, vm_directory: Path, _provider: Box
) -> None:
    stage.inject(
        host,
        vm_directory / "config.ini",
        NIX_CONFIG,
        "Provider config",
        override="config.ini",
    )


# ------------------------------------------------------------------ dispatch
# Keyed by the parsed Simulator, so matching is case-insensitive -- the same
# rule validation applies. The stages look these up; the sets name the family
# behaviour the old prefix/suffix string matching expressed.

POWER_WORLD_FAMILY: Final[tuple[Simulator, ...]] = (
    Simulator.POWER_WORLD,
    Simulator.POWER_WORLD_HELICS,
    Simulator.POWER_WORLD_DYNAMICS,
)

HELICS_FAMILY: Final[tuple[Simulator, ...]] = (
    Simulator.HELICS,
    Simulator.POWER_WORLD_HELICS,
)

YAML_CONFIGURED: Final[tuple[Simulator, ...]] = (
    Simulator.RTDS,
    Simulator.OPALRT,
    Simulator.SIREN,
)

# What configure declares per simulator; anything unlisted gets
# default_injections, and YAML_CONFIGURED simulators add yaml_config_injections.
INJECTIONS: Final[dict[Simulator, Callable[..., None]]] = {
    Simulator.POWER_WORLD: power_world_injections,
    Simulator.POWER_WORLD_HELICS: power_world_injections,
    Simulator.POWER_WORLD_DYNAMICS: power_world_dynamics_injections,
    Simulator.SIMULINK: simulink_injections,
    Simulator.PYPOWER: pypower_injections,
    Simulator.GENERIC_PYTHON: generic_python_injections,
}
