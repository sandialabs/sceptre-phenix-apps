"""Harden: close the "default to open" accounts at experiment start.

In pre-start this app gives each hardenable VM its own self-deleting script
to set passwords, remove accounts, and close root and empty-password SSH logins.
"""

from pathlib import Path, PurePosixPath
from typing import Final, cast

import yaml
from box import Box
from pydantic import BaseModel, Field

from phenix_apps.apps import AppBase
from phenix_apps.apps.harden.models import (
    Autologon,
    HardenMetadata,
    LinuxSpec,
    Password,
    SshSpec,
    Username,
    WindowsSpec,
    WindowsUsername,
    derive_password,
)
from phenix_apps.common import utils
from phenix_apps.common.base import LINUX_OS_TYPES, WINDOWS_OS_TYPE, OsType
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger
from phenix_apps.common.metadata import (
    Hostname,
    MetadataBlock,
    parse_metadata,
    validate_metadata,
)

# 50 sorts after phenix core startup scripts are done
LINUX_SCRIPT: Final[PurePosixPath] = PurePosixPath("/etc/phenix/startup/50-harden.sh")
WINDOWS_SCRIPT: Final[PurePosixPath] = PurePosixPath("/phenix/startup/50-harden.ps1")


class HostPlan(BaseModel):
    """Everything the app will do to one VM."""

    hostname: Hostname
    os_type: OsType
    users: dict[Username | WindowsUsername, Password] = Field(default_factory=dict)
    remove_users: list[Username | WindowsUsername] = Field(default_factory=list)
    ssh: SshSpec = SshSpec()
    autologon: Autologon = "keep"

    @property
    def windows(self) -> bool:
        return self.os_type == WINDOWS_OS_TYPE

    def record(self) -> dict:
        """The host's entry in the credentials file."""

        return {
            "os": self.os_type,
            "users": dict(self.users),
            "removed": list(self.remove_users),
        }


class Harden(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.config = parse_metadata(HardenMetadata, self.metadata, self.name, "app")
        self.harden_dir = Path(self.exp_dir) / "harden"

    def pre_start(self) -> None:
        plans = self.plan()

        if not plans:
            logger.warning(f"{self.name}: no hardenable VM in the experiment")
            return

        self.harden_dir.mkdir(parents=True, exist_ok=True)

        for plan in plans:
            script = self.render_script(plan)
            self.add_inject(
                plan.hostname,
                {
                    "src": str(script),
                    "dst": str(WINDOWS_SCRIPT if plan.windows else LINUX_SCRIPT),
                    "permissions": "0600",
                    "description": f"{self.name} startup script",
                },
            )
            logger.info(f"{self.name}: {plan.hostname} is hardened at boot")

        self.write_credentials(plans)

    # -- planning ----------------------------------------------------------

    def plan(self) -> list[HostPlan]:
        """One plan per hardenable VM: the OS block, with the host's own
        metadata merged over it, and every generated password derived."""

        nodes = {
            node.general.hostname: node for node in self.experiment.spec.topology.nodes
        }
        overrides: dict[str, dict] = {}

        for hostname in self.config.exclude:
            if hostname not in nodes:
                raise AppError(
                    f"{self.name} excluded host '{hostname}' is not in the topology"
                )

        for host in (self.app or Box()).get("hosts") or []:
            hostname = host.hostname
            if hostname not in nodes:
                raise AppError(f"{self.name} host '{hostname}' is not in the topology")
            if hostname in self.config.exclude:
                raise AppError(f"{self.name} host '{hostname}' is also excluded")
            overrides[hostname] = host.get("metadata") or {}

        plans = []
        refused = []

        for hostname, node in nodes.items():
            os_type = self.extract_node_os_type(hostname)
            hardenable = os_type in LINUX_OS_TYPES or os_type == WINDOWS_OS_TYPE

            if (
                hostname in self.config.exclude
                or not hardenable
                or node.get("type") == "Router"
                or node.get("external")
                or not self.is_booting(hostname)
            ):
                if hostname in overrides:
                    raise AppError(
                        f"{self.name} host '{hostname}' cannot be hardened (a router, "
                        f"external, not booting, or os_type '{os_type or 'unset'}')"
                    )
                logger.info(
                    f"{self.name}: skipping {hostname} ({os_type or 'external'})"
                )
                continue

            why = self.refusal(node, os_type, hostname in overrides)
            if why:
                refused.append(f"{hostname}: {why}")
                continue

            plans.append(self.plan_host(hostname, os_type, overrides.get(hostname)))

        if refused:
            raise AppError(
                f"{self.name} refuses {len(refused)} VM(s): " + "; ".join(refused)
            )

        return plans

    @staticmethod
    def refusal(node: Box, os_type: str, explicit: bool) -> str | None:
        """Why the startup script would never run, or do harm, on this VM."""

        annotations = node.get("annotations") or {}
        drives = (node.get("hardware") or {}).get("drives") or []

        if utils.annotation_true(node, "phenix/startup-via-cc"):
            return "phenix/startup-via-cc leaves the startup folder unrun; exclude it"
        if "disable-injects" in (node.get("labels") or {}):
            return "the disable-injects label blocks the script; exclude it"
        if drives and drives[0].get("inject_partition") == 0:
            return "inject_partition 0 blocks the script; exclude it"
        if (node.get("general") or {}).get("snapshot") is False:
            return "snapshot false blocks the script; exclude it"
        if (
            os_type == WINDOWS_OS_TYPE
            and annotations.get("phenix/default-apps") is False
        ):
            return "without phenix core's startup script the harden script never runs; exclude it"
        if not explicit and utils.annotation_true(node, "phenix/domain-controller"):
            return "a domain controller's accounts are the domain's; exclude it, or give it a hosts entry"

        return None

    def plan_host(self, hostname: str, os_type: str, override: dict | None) -> HostPlan:
        spec = self.host_spec(hostname, os_type, override)
        users = {}

        for username, user in spec.users.items():
            if user.generate:
                if self.config.seed is None:
                    raise AppError(
                        f"{self.name}: 'seed' is required to generate the password "
                        f"of '{username}' on '{hostname}'"
                    )
                users[username] = derive_password(self.config.seed, hostname, username)
            else:
                users[username] = str(user.password)

        plan = HostPlan(
            hostname=hostname,
            os_type=cast(OsType, os_type),
            users=users,
            remove_users=spec.remove_users,
        )
        if isinstance(spec, WindowsSpec):
            plan.autologon = spec.autologon
        else:
            plan.ssh = spec.ssh

        return plan

    def host_spec(
        self, hostname: str, os_type: str, override: dict | None
    ) -> LinuxSpec | WindowsSpec:
        """The OS block, with a host's explicitly set fields over it: users
        merged by name, a nested block field by field, anything else replaced."""

        kind = f"{self.name} host"

        if os_type == WINDOWS_OS_TYPE:
            if override is None:
                return self.config.windows
            own = parse_metadata(WindowsSpec, override, hostname, kind)
            merged = self.merge(self.config.windows, own)
            return validate_metadata(WindowsSpec, merged, hostname, kind)[0]

        if override is None:
            return self.config.linux
        own_linux = parse_metadata(LinuxSpec, override, hostname, kind)
        merged = self.merge(self.config.linux, own_linux)
        return validate_metadata(LinuxSpec, merged, hostname, kind)[0]

    @staticmethod
    def merge(base: LinuxSpec | WindowsSpec, own: LinuxSpec | WindowsSpec) -> dict:
        merged = base.model_dump()
        own_dump = own.model_dump()

        for name in own.model_fields_set:
            value = getattr(own, name)
            if name == "users":
                merged["users"] = {**merged["users"], **own_dump["users"]}
            elif isinstance(value, MetadataBlock):
                own_fields = {k: own_dump[name][k] for k in value.model_fields_set}
                merged[name] = {**merged[name], **own_fields}
            else:
                merged[name] = own_dump[name]

        return merged

    # -- output ------------------------------------------------------------

    def render_script(self, plan: HostPlan) -> Path:
        suffix = "ps1" if plan.windows else "sh"
        path = utils.safe_join(self.harden_dir, f"{plan.hostname}.{suffix}")

        if plan.windows:
            self.render(
                "windows.ps1.mako",
                str(path),
                hostname=plan.hostname,
                users={n: p.replace("'", "''") for n, p in plan.users.items()},
                remove_users=plan.remove_users,
                autologon=plan.autologon,
            )
        else:
            self.render(
                "linux.sh.mako",
                str(path),
                hostname=plan.hostname,
                users=plan.users,
                remove_users=plan.remove_users,
                ssh=plan.ssh,
            )

        path.chmod(0o600)
        return path

    def write_credentials(self, plans: list[HostPlan]) -> None:
        """Record every password set and account removed, in a 0600 file."""

        path = self.harden_dir / "credentials.yml"
        hosts = {plan.hostname: plan.record() for plan in plans}
        path.write_text(yaml.safe_dump({"hosts": hosts}, sort_keys=True))
        path.chmod(0o600)
