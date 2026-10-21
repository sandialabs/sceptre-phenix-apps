import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, Field, IPvAnyAddress, field_validator, model_validator

from phenix_apps.apps import AppBase
from phenix_apps.apps.otsim.points import OutstationPoint, Outstations
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# Templates
TEMPLATES_DIR: Final = Path(Path(__file__).parent, "templates")
PERSPECTIVE_TEMPLATES_DIR: Final = Path(TEMPLATES_DIR, "perspective")
API_TEMPLATES_DIR: Final = Path(TEMPLATES_DIR, "api")
TAG_FOLDER_RESOURCE_FILE: Final = Path(TEMPLATES_DIR, "tag-folder-resource.json")
TAG_SYNC_TAG_FILE: Final = Path(TEMPLATES_DIR, "tag-sync-tag.json")
TAG_SYNC_SCRIPT_FILE: Final = Path(TEMPLATES_DIR, "tag-sync.py")
# installed packages compile the Jython templates; keep the bytecode out of projects
IGNORE_PYCACHE: Final = shutil.ignore_patterns("__pycache__")

# hosts: types
GATEWAY_TYPE: Final = "gateway"
PERSPECTIVE_TYPE: Final = "perspective"

# Fixed project name for the WebDev tag API
API_PROJECT_NAME: Final = "api"
HISTORY_PROVIDER_NAME: Final = "phenix-history"
TAG_SYNC_NAME: Final = "_TagSync_"

# How the Ignition 8.3 DNP3 driver names the points it browses
OPC_SERVER: Final = "Ignition OPC UA Server"
OPC_ITEM_PATH: Final = "ns=1;s=[{device}]{point}{index}"
POINT_NAMES: Final = {
    "ai": "AnalogInput",
    "ao": "AnalogOutput",
    "bi": "BinaryInput",
    "bo": "BinaryOutput",
}
# Ignition tag and folder naming rules
TAG_NAME: Final = re.compile(r"[A-Za-z0-9_ '\-:()]{1,255}")
# the driver's own connection diagnostics, browsed as "[Diagnostics]/<name>"
DIAGNOSTICS_FOLDER: Final = "_Diagnostics_"
DIAGNOSTICS: Final = {"Hostname": "String", "Port": "Int4", "Status": "String"}

# gwbk staging path on both guest OSes (drive-relative on Windows)
GUEST_GWBK_DST: Final = "/restore.gwbk"


@dataclass(frozen=True)
class GuestLayout:
    """Where the app's files land on a guest, by OS.

    `data_dir` is the Ignition data tree: drive-relative on Windows, where
    minimega injects into the system partition, and `/opt/ignition/data` on
    Linux. Both OSes are expected to run the gateway as an `ignition` service.
    """

    data_dir: str
    startup_dir: str
    user_startup_dir: str
    script_ext: str
    newline: str

    def resource(self, *parts: str) -> str:
        return Path(self.data_dir, "config", "resources", "core", *parts).as_posix()

    @property
    def resource_dir(self) -> str:
        return self.resource()

    @property
    def device_dir(self) -> str:
        return self.resource("com.inductiveautomation.opcua", "device")

    @property
    def tag_dir(self) -> str:
        return self.resource("ignition", "tag-definition", "default")

    @property
    def database_dir(self) -> str:
        return self.resource("ignition", "database-connection")

    @property
    def history_dir(self) -> str:
        return self.resource("com.inductiveautomation.historian", "historian-provider")

    @property
    def projects_dir(self) -> str:
        return Path(self.data_dir, "projects").as_posix()

    def script_dst(self, name: str, user: bool = False) -> str:
        base = self.user_startup_dir if user else self.startup_dir
        return f"{base}/{name}{self.script_ext}"


# Windows images run /phenix/startup as SYSTEM and /phenix/user-startup at logon
WINDOWS: Final = GuestLayout(
    data_dir="Program Files/Inductive Automation/Ignition/data",
    startup_dir="/phenix/startup",
    user_startup_dir="/phenix/user-startup",
    script_ext=".ps1",
    newline="\r\n",
)
# Linux images run /etc/phenix/startup as root
LINUX: Final = GuestLayout(
    data_dir="/opt/ignition/data",
    startup_dir="/etc/phenix/startup",
    user_startup_dir="/phenix/user-startup",
    script_ext=".sh",
    newline="\n",
)
LAYOUTS: Final = {"windows": WINDOWS, "linux": LINUX}
# Linux GUI images autologin root into XFCE; this autostart entry runs the
# client script, since nothing else runs /phenix/user-startup there
LINUX_AUTOSTART_FILE: Final = "99-ignition-perspective.desktop"
LINUX_AUTOSTART_DST: Final = f"/root/.config/autostart/phenix-{LINUX_AUTOSTART_FILE}"


def guest_layout(host: Any) -> GuestLayout:
    """The layout for a host's `hardware.os_type`; phenix defaults it to linux."""
    topology = host.get("topology") or {}
    os_type = (topology.get("hardware") or {}).get("os_type") or "linux"
    try:
        return LAYOUTS[os_type.lower()]
    except KeyError:
        raise ValueError(
            f"'{host.hostname}' has os_type '{os_type}'; the ignition app "
            f"supports {sorted(LAYOUTS)}"
        ) from None


PollPeriod = Annotated[int, Field(ge=0, le=2147483647)]


class PollingConfig(BaseModel):
    """DNP3 master poll periods in milliseconds; 0 disables that poll."""

    class1: PollPeriod = 5000
    class2: PollPeriod = 5000
    class3: PollPeriod = 5000
    integrity: PollPeriod = 300000

    model_config = {"extra": "forbid"}


class RtuDeviceConfig(BaseModel):
    """DNP3 outstation connection settings RTU."""

    hostname: str
    name: str | None = None
    port: Annotated[int, Field(ge=1, le=65535)] = 20000
    # Default to ot-sim expectations
    source_address: Annotated[int, Field(ge=1, le=1024)] = 1
    destination_address: Annotated[int, Field(ge=1, le=1024)] = 1024
    interface: str | None = None
    polling: PollingConfig | None = None
    # auto: semantic tags when the RTU is an ot-sim outstation, else discovery
    points: Literal["auto", "otsim", "discover"] = "auto"

    model_config = {"extra": "ignore"}

    @field_validator("name")
    @classmethod
    def _validate_device_name(cls, v: str | None) -> str | None:
        if v is not None and (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_ -]{1,62}", v)
            or v.lower() in utils.RESERVED_HOSTNAMES
        ):
            raise ValueError(
                "device names must be 2 to 63 letters, digits, spaces, '_' and "
                "'-', start with a letter or digit, and not be 'all' or 'phenix'"
            )
        return v

    @property
    def resolved_name(self) -> str:
        return self.name or self.hostname

    def resolved_polling(self, default: PollingConfig) -> PollingConfig:
        """Per-RTU poll periods override the gateway's field by field."""
        if self.polling is None:
            return default
        return default.model_copy(update=self.polling.model_dump(exclude_unset=True))


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
    the gateway's config tree before boot. RTUs that are ot-sim outstations
    get a tag tree named after the ot-sim devices and variables they serve;
    other RTUs get their points discovered on the gateway. `perspective`
    optionally builds a basic HMI project on top of them. `polling` sets the
    DNP3 poll periods for every connected RTU; an RTU's own `polling`
    overrides it per field.

    With `gwbk`, the given gateway backup is
    restored verbatim at boot instead.

    `api` optionally serves a WebDev tag API and is independent of both
    `perspective` and `connected_rtus`. `historian` enables native PostgreSQL
    tag history and shares tag discovery with Perspective. `gwbk` is mutually
    exclusive with the other options.
    """

    gwbk: str | None = None
    connected_rtus: list[RtuDeviceConfig] = Field(default_factory=list)
    polling: PollingConfig = Field(default_factory=PollingConfig)
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
        if "polling" in self.model_fields_set and not self.connected_rtus:
            raise ValueError(
                "'polling' sets poll periods on connected_rtus devices and has "
                "no effect without them; configure existing devices on the "
                "gateway or in the gwbk instead"
            )
        return self


class PerspectiveClientConfig(BaseModel):
    """Per-host metadata for a `type: perspective` node (dedicated HMI desktop)."""

    connected_gateway: str | None = None
    interface: str | None = None

    model_config = {"extra": "ignore"}


def history_properties(provider: str) -> dict[str, Any]:
    """On-change OPC history, mirroring the point as Ignition observes it."""
    return {
        "historyEnabled": True,
        "historyProvider": provider,
        "sampleMode": "OnChange",
        "historicalDeadbandStyle": "Discrete",
        "historicalDeadbandMode": "Absolute",
        "historicalDeadband": 0.0,
        "historyTimeDeadband": 0,
        "historyMaxAge": 0,
    }


def opc_item_path(device: str, kind: str, index: int) -> str:
    return OPC_ITEM_PATH.format(device=device, point=POINT_NAMES[kind], index=index)


def tag_name(name: str, context: str) -> str:
    if not TAG_NAME.fullmatch(name):
        raise ValueError(
            f"{context}: '{name}' is not a valid Ignition tag name (letters, "
            "digits, spaces, _ ' - : ( ) only, up to 255 characters)"
        )
    return name


def device_tag_folder(
    device: dict[str, Any], history: dict[str, Any] | None
) -> dict[str, Any]:
    """`<device>/<ot-sim device>/<variable>` OPC tags for a mapped device."""
    name = device["name"]
    folders: dict[str, dict[str, Any]] = {}
    seen: dict[tuple[str, str], OutstationPoint] = {}

    for point in device["points"]:
        context = f"device '{name}' ot-sim device '{point.device}'"
        tag_name(point.device, f"device '{name}'")
        if point.device == DIAGNOSTICS_FOLDER:
            raise ValueError(f"{context}: name is reserved for driver diagnostics")
        tag_name(point.variable, context)
        if (point.device, point.variable) in seen:
            other = seen[point.device, point.variable]
            raise ValueError(
                f"{context} variable '{point.variable}' is served twice "
                f"({POINT_NAMES[other.kind]}{other.index} and "
                f"{POINT_NAMES[point.kind]}{point.index}); set points: discover "
                "on this RTU to import it by DNP3 address instead"
            )
        seen[point.device, point.variable] = point

        tag = {
            "name": point.variable,
            "tagType": "AtomicTag",
            "valueSource": "opc",
            "opcServer": OPC_SERVER,
            "opcItemPath": opc_item_path(name, point.kind, point.index),
            "dataType": "Float8" if point.analog else "Boolean",
            # Ignition's default deadband would hide small per-unit changes
            "deadband": 0.0,
            "tooltip": f"{point.device_type} {point.device}",
            "documentation": (
                f"{point.device_type} {point.device} "
                f"(ot-sim, DNP3 {POINT_NAMES[point.kind]} {point.index})"
            ),
        }
        if not point.writable:
            tag["readOnly"] = True
        if history:
            tag.update(history)

        folder = folders.setdefault(
            point.device, {"name": point.device, "tagType": "Folder", "tags": []}
        )
        folder["tags"].append(tag)

    folders[DIAGNOSTICS_FOLDER] = diagnostics_tag_folder(name)
    return {"name": name, "tagType": "Folder", "tags": list(folders.values())}


def diagnostics_tag_folder(device: str) -> dict[str, Any]:
    """The driver diagnostics the overview reads, as discovery would import them."""
    return {
        "name": DIAGNOSTICS_FOLDER,
        "tagType": "Folder",
        "tags": [
            {
                "name": diag,
                "tagType": "AtomicTag",
                "valueSource": "opc",
                "opcServer": OPC_SERVER,
                "opcItemPath": f"ns=1;s=[{device}][Diagnostics]/{diag}",
                "dataType": data_type,
                "readOnly": True,
                "documentation": f"DNP3 driver {diag.lower()} for {device}",
            }
            for diag, data_type in DIAGNOSTICS.items()
        ],
    }


def tag_sync_tag(mapped_devices: list[str], history: dict[str, Any] | None) -> dict:
    """The expression tag whose event script discovers the points of every
    device not in `mapped_devices` and imports them under their DNP3 names."""
    tag = json.loads(TAG_SYNC_TAG_FILE.read_text())
    script = TAG_SYNC_SCRIPT_FILE.read_text()
    # the script is Jython: these literals are valid there too
    tag["eventScripts"][0]["script"] = (
        f"\tmapped_devices = {mapped_devices!r}\n\thistory = {history!r}\n" + script
    )
    return tag


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
        layout = guest_layout(gateway)

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
                    "dst": GUEST_GWBK_DST,
                },
            )
        else:
            devices = self._resolve_devices(cfg.connected_rtus, cfg.polling)
            self._validate_unique_names(devices)
            for src, dst in self._write_device_tree(host_dir, layout, devices):
                self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})
            if cfg.historian:
                self._write_historian(hostname, host_dir, layout, cfg.historian)
            if cfg.perspective or cfg.historian or cfg.api:
                tags_dir = Path(host_dir, "tags")
                self._write_tag_tree(
                    tags_dir, devices, historian=cfg.historian is not None
                )
                for src, dst in self._tree_injects(tags_dir, layout.tag_dir):
                    self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})
            if cfg.perspective:
                self._write_perspective(
                    hostname, host_dir, layout, cfg.perspective, devices
                )
                if cfg.perspective.open_client:
                    url = (
                        "http://localhost:8088/data/perspective/client/"
                        f"{cfg.perspective.project}"
                    )
                    self._inject_open_client_script(hostname, host_dir, layout, url)
            if cfg.api:
                self._write_api(hostname, host_dir, layout, cfg.api)

        # stops the gateway, stages any gwbk restore and starts the service again
        self._inject_script(hostname, host_dir, layout, "98-ignition")

        return cfg

    def _inject_script(
        self,
        hostname: str,
        host_dir: Path,
        layout: GuestLayout,
        name: str,
        user: bool = False,
        **kwargs: Any,
    ) -> None:
        """Render the guest OS flavour of a boot script and inject it."""
        filename = f"{name}{layout.script_ext}"
        script = Path(host_dir, filename)
        with script.open("w", newline=layout.newline) as f:
            utils.mako_serve_template(f"{filename}.mako", TEMPLATES_DIR, f, **kwargs)
        self.add_inject(
            hostname=hostname,
            inject={"src": script.as_posix(), "dst": layout.script_dst(name, user)},
        )

    def _resolve_devices(
        self, rtus: list[RtuDeviceConfig], polling: PollingConfig | None = None
    ) -> list[dict[str, Any]]:
        polling = polling or PollingConfig()
        outstations = Outstations(self.extract_app("ot-sim"), self.extract_node)
        devices = []

        for rtu in rtus:
            points = self._map_points(rtu, outstations)
            ip, port = None, rtu.port
            if points is not None:
                # ot-sim knows where its outstation listens
                otsim_ip, otsim_port = outstations.endpoint(rtu.hostname)
                if "interface" not in rtu.model_fields_set:
                    ip = otsim_ip
                if "port" not in rtu.model_fields_set:
                    port = otsim_port
            try:
                ip = ip or self.extract_node_ip(rtu.hostname, rtu.interface)
            except ValueError as ex:
                msg = (
                    f"RTU '{rtu.hostname}' has no addressed interface "
                    f"'{rtu.interface or '(first)'}' in the topology: {ex}"
                )
                if not self.dryrun:
                    raise ValueError(msg) from ex
                logger.warning(f"Dry run: {msg}; using placeholder IP")
                ip = "127.0.0.1"

            devices.append(
                {
                    "name": rtu.resolved_name,
                    "ip": ip,
                    "port": port,
                    "source_address": rtu.source_address,
                    "destination_address": rtu.destination_address,
                    "polling": rtu.resolved_polling(polling).model_dump(),
                    "points": points,
                }
            )

        return devices

    @staticmethod
    def _map_points(
        rtu: RtuDeviceConfig, outstations: Outstations
    ) -> list[OutstationPoint] | None:
        """ot-sim's point list for the RTU, or None to discover points on the
        gateway instead."""
        if rtu.points == "discover":
            return None
        if rtu.hostname in outstations:
            points = outstations.points(rtu.hostname)
            logger.info(
                f"RTU '{rtu.hostname}': {len(points)} DNP3 points mapped from ot-sim"
            )
            return points
        if rtu.points == "otsim":
            raise ValueError(
                f"RTU '{rtu.hostname}' has points: otsim but is not an ot-sim host "
                "in this scenario"
            )
        logger.info(
            f"RTU '{rtu.hostname}' is not an ot-sim host; its points will be "
            "discovered on the gateway"
        )
        return None

    @staticmethod
    def _validate_unique_names(devices: list[dict[str, Any]]) -> None:
        names = [d["name"] for d in devices]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"Duplicate device name(s) in connected_rtus: {sorted(dupes)}"
            )

    def _write_device_tree(
        self, host_dir: Path, layout: GuestLayout, devices: list[dict[str, Any]]
    ) -> list[tuple[str, str]]:
        """Render one device resource folder per RTU, returning (src, dst) injects."""
        injects = []

        for device in devices:
            device_dir = utils.safe_join(host_dir, "devices", device["name"])
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
                        Path(layout.device_dir, device["name"], fname).as_posix(),
                    )
                )

        return injects

    def _write_perspective(
        self,
        hostname: str,
        host_dir: Path,
        layout: GuestLayout,
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
            project_dir, Path(layout.projects_dir, pcfg.project)
        ):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    def _write_historian(
        self, hostname: str, host_dir: Path, layout: GuestLayout, hcfg: HistorianConfig
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
        for src, dst in self._tree_injects(build_dir, layout.resource_dir):
            self.add_inject(hostname=hostname, inject={"src": src, "dst": dst})

    def _write_api(
        self, hostname: str, host_dir: Path, layout: GuestLayout, acfg: ApiConfig
    ) -> None:
        """Render the WebDev tag-API project and inject it file-by-file into
        the gateway's data tree. Independent of perspective and connected_rtus:
        the resource browses the OPC server live at request time."""
        project_dir = Path(host_dir, "api", "project", API_PROJECT_NAME)
        self._write_api_project(project_dir, acfg)
        dst_dir = Path(layout.projects_dir, API_PROJECT_NAME)
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
        shutil.copytree(API_TEMPLATES_DIR, project_dir, ignore=IGNORE_PYCACHE)

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
    def _tree_injects(src_dir: Path, dst_dir: str | Path) -> list[tuple[str, str]]:
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
        shutil.copytree(PERSPECTIVE_TEMPLATES_DIR, project_dir, ignore=IGNORE_PYCACHE)

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
    def _write_tag_tree(
        tags_dir: Path, devices: list[dict[str, Any]], historian: bool = False
    ) -> None:
        """Seed the `[default]` provider: one folder of named tags per device
        mapped from ot-sim, plus the tag-sync heartbeat when any device's
        points still have to be discovered gateway-side."""
        tags_dir.mkdir(parents=True, exist_ok=True)

        with TAG_FOLDER_RESOURCE_FILE.open() as f:
            resource = json.load(f)
        resource["files"] = ["tags.json"]

        history = history_properties(HISTORY_PROVIDER_NAME) if historian else None
        tags = [
            device_tag_folder(device, history)
            for device in devices
            if device["points"] is not None
        ]
        mapped = [tag["name"] for tag in tags]
        # without connected RTUs the sync also picks up devices already on the gateway
        if len(mapped) < len(devices) or not devices:
            tags.append(tag_sync_tag(mapped, history))

        with Path(tags_dir, "tags.json").open("w") as f:
            json.dump(tags, f, indent=2)
        with Path(tags_dir, "unary-resource.json").open("w") as f:
            json.dump(resource, f, indent=2)

    def _configure_perspective_client(
        self, client, gateways: dict[str, PerspectiveConfig]
    ) -> None:
        hostname = client.hostname
        cfg = PerspectiveClientConfig(**client.metadata)
        layout = guest_layout(client)

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

        try:
            ip = self.extract_node_ip(gw_hostname, cfg.interface)
        except ValueError as ex:
            msg = (
                f"gateway '{gw_hostname}' has no addressed interface "
                f"'{cfg.interface or '(first)'}' in the topology: {ex}"
            )
            if not self.dryrun:
                raise ValueError(msg) from ex
            logger.warning(f"Dry run: {msg}; using placeholder IP")
            ip = "127.0.0.1"

        host_dir = Path(self.app_dir, hostname)
        host_dir.mkdir(parents=True, exist_ok=True)

        url = (
            f"http://{ip}:8088/data/perspective/client/{gateways[gw_hostname].project}"
        )
        self._inject_open_client_script(hostname, host_dir, layout, url)

    def _inject_open_client_script(
        self, hostname: str, host_dir: Path, layout: GuestLayout, url: str
    ) -> None:
        """Logon script that opens the HMI page in a browser."""
        self._inject_script(
            hostname, host_dir, layout, "99-ignition-perspective", user=True, url=url
        )
        if layout is LINUX:
            autostart = Path(host_dir, LINUX_AUTOSTART_FILE)
            shutil.copy(Path(TEMPLATES_DIR, LINUX_AUTOSTART_FILE), autostart)
            self.add_inject(
                hostname=hostname,
                inject={"src": autostart.as_posix(), "dst": LINUX_AUTOSTART_DST},
            )
