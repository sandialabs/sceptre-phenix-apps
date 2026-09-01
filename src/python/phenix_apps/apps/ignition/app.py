import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, Field, IPvAnyAddress, field_validator, model_validator

from phenix_apps.apps import AppBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# Templates
TEMPLATES_DIR = Path(Path(__file__).parent, "templates")
PERSPECTIVE_TEMPLATES_DIR = Path(TEMPLATES_DIR, "perspective")
API_TEMPLATES_DIR = Path(TEMPLATES_DIR, "api")
TAG_FOLDER_RESOURCE_FILE = Path(TEMPLATES_DIR, "tag-folder-resource.json")
TAG_SYNC_TAG_FILE = Path(TEMPLATES_DIR, "tag-sync-tag.json")
TAG_SYNC_SCRIPT_FILE = Path(TEMPLATES_DIR, "tag-sync.py")

# hosts: types
GATEWAY_TYPE = "gateway"
PERSPECTIVE_TYPE = "perspective"

# Fixed project name for the WebDev tag API
API_PROJECT_NAME = "api"
HISTORY_PROVIDER_NAME = "phenix-history"

# expect windows, built with /phenix/startup and /phenix/user-startup
GUEST_APP_DIR = "/phenix/ignition"
GUEST_GWBK_SCRIPT_DST = "/phenix/startup/98-ignition.ps1"
GUEST_CLIENT_SCRIPT_DST = "/phenix/user-startup/99-ignition-perspective.ps1"
# Ignition program paths
GUEST_DATA_DIR = "Program Files/Inductive Automation/Ignition/data"
GUEST_DEVICE_DIR = Path(
    GUEST_DATA_DIR,
    "config",
    "resources",
    "core",
    "com.inductiveautomation.opcua",
    "device",
)
GUEST_TAG_DIR = Path(
    GUEST_DATA_DIR,
    "config",
    "resources",
    "core",
    "ignition",
    "tag-definition",
    "default",
)
GUEST_PROJECTS_DIR = Path(GUEST_DATA_DIR, "projects")
GUEST_RESOURCE_DIR = Path(GUEST_DATA_DIR, "config", "resources", "core")
GUEST_DATABASE_DIR = Path(GUEST_RESOURCE_DIR, "ignition", "database-connection")
GUEST_HISTORY_DIR = Path(
    GUEST_RESOURCE_DIR, "com.inductiveautomation.historian", "historian-provider"
)


class RtuDeviceConfig(BaseModel):
    """DNP3 outstation connection settings RTU."""

    hostname: str
    name: str | None = None
    port: Annotated[int, Field(ge=1, le=65535)] = 20000
    # Default to ot-sim expectations
    source_address: Annotated[int, Field(ge=1, le=1024)] = 1
    destination_address: Annotated[int, Field(ge=1, le=1024)] = 1024
    interface: str | None = None

    model_config = {"extra": "ignore"}

    @property
    def resolved_name(self) -> str:
        return self.name or self.hostname


class PerspectiveConfig(BaseModel):
    """Perspective HMI options for a gateway (`perspective: true` for defaults)."""

    project: str = "hmi"
    open_client: bool = True

    model_config = {"extra": "ignore"}

    @field_validator("project")
    @classmethod
    def _validate_project_name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", v):
            raise ValueError(
                "perspective project names may only contain letters, digits, "
                "'_' and '-'"
            )
        return v


class ApiConfig(BaseModel):
    """WebDev tag API options for a gateway (`api: true` for defaults).

    Serves a `tags` WebDev resource at
    `http://<gateway>:8088/system/webdev/api/tags`: GET reads every DNP3 point
    from the OPC server, POST issues an explicitly typed analog or binary
    DNP3 command. `auth`
    requires HTTP Basic auth on the POST (control) endpoint, validated against
    `user_source` and optionally restricted to `roles`; `require_https` enforces
    HTTPS on controls. Reads stay open.
    """

    auth: bool = False
    require_https: bool = False
    roles: list[str] = Field(default_factory=list)
    user_source: str = "default"

    model_config = {"extra": "ignore"}


class HistorianConfig(BaseModel):
    """Passwordless connection to an existing PostgreSQL history database."""

    ip: IPvAnyAddress
    port: Annotated[int, Field(ge=1, le=65535)] = 5432
    user: str = "ignition"
    database: str = "ignition"

    model_config = {"extra": "forbid"}


class IgnitionHostConfig(BaseModel):
    """Per-host metadata for a `type: gateway` node.

    With `connected_rtus`, rendered DNP3 device resources are injected into
    the gateway's config tree before boot, and `perspective` optionally builds
    a basic HMI project on top of them whose tags auto-import from whatever
    points the devices actually serve.

    With `gwbk`, the given gateway backup is
    restored verbatim at boot instead.

    `api` optionally serves a WebDev tag API and is independent of both
    `perspective` and `connected_rtus`. `historian` enables native PostgreSQL
    tag history and shares tag discovery with Perspective. `gwbk` is mutually
    exclusive with the other options.
    """

    gwbk: str | None = None
    connected_rtus: list[RtuDeviceConfig] = Field(default_factory=list)
    perspective: PerspectiveConfig | None = None
    api: ApiConfig | None = None
    historian: HistorianConfig | None = None

    model_config = {"extra": "ignore", "hide_input_in_errors": True}

    @field_validator("connected_rtus", mode="before")
    @classmethod
    def _normalize_rtus(cls, v: Any) -> list[Any]:
        """Allow plain hostname strings alongside dict overrides."""
        if not v:
            return []
        return [{"hostname": e} if isinstance(e, str) else e for e in v]

    @field_validator("perspective", mode="before")
    @classmethod
    def _normalize_perspective(cls, v: Any) -> Any:
        """Allow `perspective: true` as shorthand for the defaults."""
        if v is True:
            return PerspectiveConfig()
        if v is False:
            return None
        return v

    @field_validator("api", mode="before")
    @classmethod
    def _normalize_api(cls, v: Any) -> Any:
        """Allow `api: true` as shorthand for the defaults."""
        if v is True:
            return ApiConfig()
        if v is False:
            return None
        return v

    @field_validator("historian", mode="before")
    @classmethod
    def _normalize_historian(cls, v: Any) -> Any:
        if v is True:
            raise ValueError(
                "'historian: true' has no connection details; supply ip, user, "
                "and database (port defaults to 5432); PostgreSQL must allow "
                "passwordless authentication"
            )
        if v is False:
            return None
        return v

    @model_validator(mode="after")
    def _gwbk_excludes_extras(self) -> "IgnitionHostConfig":
        if self.gwbk and self.connected_rtus:
            raise ValueError(
                "'gwbk' restores a complete backup verbatim and cannot be "
                "combined with 'connected_rtus'; put the device connections "
                "in the backup itself"
            )
        if self.gwbk and self.perspective:
            raise ValueError(
                "'perspective' builds an HMI from connected_rtus and cannot be "
                "combined with 'gwbk'; add the HMI project to the backup itself"
            )
        if self.gwbk and self.api:
            raise ValueError(
                "'api' injects a WebDev project into the gateway's data tree "
                "and cannot be combined with 'gwbk'; add the api project to "
                "the backup itself"
            )
        if self.gwbk and self.historian:
            raise ValueError(
                "'historian' injects database, history, and tag resources and "
                "cannot be combined with 'gwbk'; configure history in the "
                "backup itself"
            )
        return self


class PerspectiveClientConfig(BaseModel):
    """Per-host metadata for a `type: perspective` node (dedicated HMI desktop)."""

    connected_gateway: str | None = None
    interface: str | None = None

    model_config = {"extra": "ignore"}


class Ignition(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.app_dir: Path = Path(self.exp_dir, "ignition")
        self.app_dir.mkdir(parents=True, exist_ok=True)

    def pre_start(self) -> None:
        logger.info(f"Starting user application: {self.name}")

        perspective_gateways: dict[str, PerspectiveConfig] = {}
        for gateway in self.extract_nodes_type(GATEWAY_TYPE):
            cfg = self._configure_gateway(gateway)
            if cfg and cfg.perspective:
                perspective_gateways[gateway.hostname] = cfg.perspective

        for client in self.extract_nodes_type(PERSPECTIVE_TYPE):
            self._configure_perspective_client(client, perspective_gateways)

        logger.info(f"Started user application: {self.name}")

    def _configure_gateway(self, gateway) -> IgnitionHostConfig | None:
        hostname = gateway.hostname
        cfg = IgnitionHostConfig(**gateway.metadata)

        if (
            not cfg.connected_rtus
            and not cfg.gwbk
            and not cfg.api
            and not cfg.historian
        ):
            logger.warning(
                f"'{hostname}' has no connected_rtus, api, historian, or gwbk; skipping"
            )
            return None

        host_dir = Path(self.app_dir, hostname)
        host_dir.mkdir(parents=True, exist_ok=True)

        if cfg.gwbk:
            if not Path(cfg.gwbk).is_file():
                if not self.dryrun:
                    raise ValueError(f"gwbk '{cfg.gwbk}' not found")
                logger.warning(f"Dry run: gwbk '{cfg.gwbk}' not found; skipping")
                return None
            self.add_inject(
                hostname=hostname,
                inject={
                    "src": cfg.gwbk,
                    "dst": Path(GUEST_APP_DIR, "restore.gwbk").as_posix(),
                },
            )
            # only a gwbk restore needs boot-time work (gwcmd on the live guest)
            script = Path(host_dir, "98-ignition.ps1")
            with script.open("w", newline="\r\n") as f:
                utils.mako_serve_template("98-ignition.ps1.mako", TEMPLATES_DIR, f)
            self.add_inject(
                hostname=hostname,
                inject={"src": script.as_posix(), "dst": GUEST_GWBK_SCRIPT_DST},
            )
        else:
            devices = self._resolve_devices(cfg.connected_rtus)
            self._validate_unique_names(devices)
            for src, dst in self._write_device_tree(host_dir, devices):
                self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})
            if cfg.historian:
                self._write_historian(hostname, host_dir, cfg.historian)
            if cfg.perspective or cfg.historian:
                tags_dir = Path(host_dir, "tags")
                self._write_tag_tree(tags_dir, historian=cfg.historian is not None)
                for src, dst in self._tree_injects(tags_dir, GUEST_TAG_DIR):
                    self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})
            if cfg.perspective:
                self._write_perspective(hostname, host_dir, cfg.perspective, devices)
                if cfg.perspective.open_client:
                    url = (
                        "http://localhost:8088/data/perspective/client/"
                        f"{cfg.perspective.project}"
                    )
                    self._inject_open_client_script(hostname, host_dir, url)
            if cfg.api:
                self._write_api(hostname, host_dir, cfg.api)

        return cfg

    def _resolve_devices(self, rtus: list[RtuDeviceConfig]) -> list[dict[str, Any]]:
        devices = []

        for rtu in rtus:
            ip = self.extract_node_interface_ip(rtu.hostname, rtu.interface)
            if not ip:
                msg = (
                    f"RTU '{rtu.hostname}' has no addressed interface "
                    f"'{rtu.interface or '(first)'}' in the topology"
                )
                if not self.dryrun:
                    raise ValueError(msg)
                logger.warning(f"Dry run: {msg}; using placeholder IP")
                ip = "127.0.0.1"

            devices.append(
                {
                    "name": rtu.resolved_name,
                    "ip": ip,
                    "port": rtu.port,
                    "source_address": rtu.source_address,
                    "destination_address": rtu.destination_address,
                }
            )

        return devices

    @staticmethod
    def _validate_unique_names(devices: list[dict[str, Any]]) -> None:
        names = [d["name"] for d in devices]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"Duplicate device name(s) in connected_rtus: {sorted(dupes)}"
            )

    def _write_device_tree(
        self, host_dir: Path, devices: list[dict[str, Any]]
    ) -> list[tuple[str, str]]:
        """Render one device resource folder per RTU, returning (src, dst) injects."""
        injects = []

        for device in devices:
            device_dir = Path(host_dir, "devices", device["name"])
            device_dir.mkdir(parents=True, exist_ok=True)

            with Path(device_dir, "config.json").open("w") as f:
                utils.mako_serve_template(
                    "dnp3-config.json.mako", TEMPLATES_DIR, f, device=device
                )
            with Path(device_dir, "resource.json").open("w") as f:
                utils.mako_serve_template(
                    "dnp3-resource.json.mako",
                    TEMPLATES_DIR,
                    f,
                    uuid=str(uuid4()),
                    timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )

            for fname in ("config.json", "resource.json"):
                injects.append(
                    (
                        Path(device_dir, fname).as_posix(),
                        Path(GUEST_DEVICE_DIR, device["name"], fname).as_posix(),
                    )
                )

        return injects

    def _write_perspective(
        self,
        hostname: str,
        host_dir: Path,
        pcfg: PerspectiveConfig,
        devices: list[dict[str, Any]],
    ) -> None:
        """Render the Perspective project, injected file-by-file."""
        build_dir = Path(host_dir, "perspective")
        project_dir = Path(build_dir, "project", pcfg.project)
        self._write_perspective_project(
            project_dir, pcfg.project, [d["name"] for d in devices]
        )
        for src, dst in self._tree_injects(
            project_dir, Path(GUEST_PROJECTS_DIR, pcfg.project)
        ):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    def _write_historian(
        self, hostname: str, host_dir: Path, hcfg: HistorianConfig
    ) -> None:
        """Inject native passwordless database/history resources before boot."""
        with Path(TEMPLATES_DIR, "historian", "database-config.json").open() as f:
            database = json.load(f)
        address = quote(hcfg.ip.compressed, safe=":")
        if ":" in address:
            address = f"[{address}]"
        database["connectURL"] = (
            f"jdbc:postgresql://{address}:{hcfg.port}/{quote(hcfg.database, safe='')}"
        )
        database["username"] = hcfg.user

        with Path(TEMPLATES_DIR, "historian", "history-config.json").open() as f:
            history = json.load(f)
        history["settings"]["database"] = HISTORY_PROVIDER_NAME

        build_dir = Path(host_dir, "historian")
        for resource_type, config in (
            (("ignition", "database-connection"), database),
            (
                ("com.inductiveautomation.historian", "historian-provider"),
                history,
            ),
        ):
            resource_dir = Path(build_dir, *resource_type, HISTORY_PROVIDER_NAME)
            resource_dir.mkdir(parents=True, exist_ok=True)
            resource = {
                "scope": "A",
                "description": "phenix native PostgreSQL tag history",
                "version": 1,
                "restricted": False,
                "overridable": True,
                "files": ["config.json"],
                "attributes": {"uuid": str(uuid4()), "enabled": True},
            }
            # Ignition maintains modification/signature metadata; do not copy
            # another resource's audit signature onto newly generated content.
            for filename, content in (
                ("config.json", config),
                ("resource.json", resource),
            ):
                with Path(resource_dir, filename).open("w") as f:
                    json.dump(content, f, indent=2)
        for src, dst in self._tree_injects(build_dir, GUEST_RESOURCE_DIR):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    def _write_api(self, hostname: str, host_dir: Path, acfg: ApiConfig) -> None:
        """Render the WebDev tag-API project and inject it file-by-file into
        the gateway's data tree. Independent of perspective and connected_rtus:
        the resource browses the OPC server live at request time."""
        project_dir = Path(host_dir, "api", "project", API_PROJECT_NAME)
        self._write_api_project(project_dir, acfg)
        dst_dir = Path(GUEST_PROJECTS_DIR, API_PROJECT_NAME)
        for src, dst in self._tree_injects(project_dir, dst_dir):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    @staticmethod
    def _write_api_project(project_dir: Path, acfg: ApiConfig) -> None:
        """Copy the WebDev project tree captured from a live 8.3 gateway, then
        patch the security settings on the `tags` resource's POST (control) method.
        The project name is fixed and reads stay open, so this is the only
        dynamic part; WebDev stores per-method auth in the resource's
        config.json."""
        if project_dir.exists():
            shutil.rmtree(project_dir)
        shutil.copytree(API_TEMPLATES_DIR, project_dir)

        config_path = Path(
            project_dir,
            "com.inductiveautomation.webdev",
            "resources",
            "tags",
            "config.json",
        )
        with config_path.open() as f:
            config = json.load(f)
        post = config["doPost"]
        post["require-auth"] = acfg.auth
        post["require-https"] = acfg.require_https
        post["required-roles"] = ",".join(acfg.roles)
        post["user-source"] = acfg.user_source if acfg.auth else ""
        with config_path.open("w") as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def _tree_injects(src_dir: Path, dst_dir: Path) -> list[tuple[str, str]]:
        """One inject per file: minimega creates missing parent directories
        per file, while copying a whole directory would nest wrongly if the
        destination already existed in the image."""
        injects = []
        for root, dirs, files in src_dir.walk():
            dirs.sort()
            rel = root.relative_to(src_dir)
            prefix = dst_dir if rel == Path(".") else Path(dst_dir, rel)
            for fname in sorted(files):
                injects.append(
                    (Path(root, fname).as_posix(), Path(prefix, fname).as_posix())
                )
        return injects

    def _write_perspective_project(
        self, project_dir: Path, project: str, device_names: list[str]
    ) -> None:
        """Copy the static project tree, then patch the two dynamic files:
        the project title and the overview view's tab list (one embedded
        station view per RTU device)."""
        if project_dir.exists():
            shutil.rmtree(project_dir)
        shutil.copytree(PERSPECTIVE_TEMPLATES_DIR, project_dir)

        path = Path(project_dir, "project.json")
        with path.open() as f:
            proj = json.load(f)
        proj["title"] = project
        with path.open("w") as f:
            json.dump(proj, f, indent=2)

        path = Path(
            project_dir,
            "com.inductiveautomation.perspective",
            "views",
            "overview",
            "view.json",
        )
        with path.open() as f:
            view = json.load(f)
        root = view["root"]
        for i, name in enumerate(device_names, start=1):
            root["props"]["tabs"].append(name)
            root["children"].append(
                {
                    "meta": {"name": f"EmbeddedView_{i}"},
                    "position": {"tabIndex": i},
                    "props": {"params": {"rtuName": name}, "path": "station"},
                    "type": "ia.display.view",
                }
            )
        with path.open("w") as f:
            json.dump(view, f, indent=2)

    @staticmethod
    def _write_tag_tree(tags_dir: Path, historian: bool = False) -> None:
        """Seed the `[default]` provider with the tag-sync heartbeat; every
        device's points are then imported gateway-side by its event script."""
        tags_dir.mkdir(parents=True, exist_ok=True)

        with TAG_FOLDER_RESOURCE_FILE.open() as f:
            resource = json.load(f)
        resource["files"] = ["tags.json"]

        with TAG_SYNC_TAG_FILE.open() as f:
            tag = json.load(f)
        with TAG_SYNC_SCRIPT_FILE.open() as f:
            provider = HISTORY_PROVIDER_NAME if historian else None
            tag["eventScripts"][0]["script"] = (
                f"\thistory_provider = {provider!r}\n" + f.read()
            )

        with Path(tags_dir, "tags.json").open("w") as f:
            json.dump([tag], f, indent=2)
        with Path(tags_dir, "unary-resource.json").open("w") as f:
            json.dump(resource, f, indent=2)

    def _configure_perspective_client(
        self, client, gateways: dict[str, PerspectiveConfig]
    ) -> None:
        hostname = client.hostname
        cfg = PerspectiveClientConfig(**client.metadata)

        if cfg.connected_gateway:
            if cfg.connected_gateway not in gateways:
                raise ValueError(
                    f"'{hostname}' connected_gateway '{cfg.connected_gateway}' "
                    "is not a perspective-enabled gateway"
                )
            gw_hostname = cfg.connected_gateway
        elif len(gateways) == 1:
            gw_hostname = next(iter(gateways))
        else:
            raise ValueError(
                f"'{hostname}' needs connected_gateway: found {len(gateways)} "
                "perspective-enabled gateways"
            )

        ip = self.extract_node_interface_ip(gw_hostname, cfg.interface)
        if not ip:
            msg = (
                f"gateway '{gw_hostname}' has no addressed interface "
                f"'{cfg.interface or '(first)'}' in the topology"
            )
            if not self.dryrun:
                raise ValueError(msg)
            logger.warning(f"Dry run: {msg}; using placeholder IP")
            ip = "127.0.0.1"

        host_dir = Path(self.app_dir, hostname)
        host_dir.mkdir(parents=True, exist_ok=True)

        url = (
            f"http://{ip}:8088/data/perspective/client/{gateways[gw_hostname].project}"
        )
        self._inject_open_client_script(hostname, host_dir, url)

    def _inject_open_client_script(
        self, hostname: str, host_dir: Path, url: str
    ) -> None:
        """Startup script that opens the HMI page in a browser."""
        script = Path(host_dir, "99-ignition-perspective.ps1")
        with script.open("w", newline="\r\n") as f:
            utils.mako_serve_template(
                "99-ignition-perspective.ps1.mako", TEMPLATES_DIR, f, url=url
            )
        self.add_inject(
            hostname=hostname,
            inject={"src": script.as_posix(), "dst": GUEST_CLIENT_SCRIPT_DST},
        )
