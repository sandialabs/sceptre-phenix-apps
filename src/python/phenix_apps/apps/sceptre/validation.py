"""Pre-flight validation of a SCEPTRE scenario.

One pydantic model for the whole app. Each host's metadata is validated against
the model for its metadata.type, and anything that needs the rest of the
scenario -- a provider name, a connected_rtus entry -- reads the lookups passed
in as validation context.

Problems are collected, not raised one at a time: malformed input comes back as
a ValidationError, every other check appends through check(). Two severities:

    fatal    the experiment cannot be built. Only for a condition that provably
             crashes the app today, so nothing that used to build is rejected.
    warning  built anyway, but almost certainly a mistake.
"""

import difflib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from phenix_apps.apps.sceptre import simulators
from phenix_apps.apps.sceptre.configs.infrastructures import INFRASTRUCTURES
from phenix_apps.apps.sceptre.hosts import describe_interfaces, is_backup, non_mgmt
from phenix_apps.apps.sceptre.metadata import DEVICE_KEYS, Infrastructure, Simulator
from phenix_apps.common import error
from phenix_apps.common.logger import logger

if TYPE_CHECKING:
    from phenix_apps.apps.sceptre.app import Sceptre

# What a check looks things up in: the problem list being built, plus the
# hostname sets it resolves references against.
Context = dict[str, Any]

# Enum members hash by name, so membership has to go through a tuple, which
# compares by value.
INFRASTRUCTURE_NAMES: Final[tuple[Infrastructure, ...]] = tuple(Infrastructure)

# Protocol metadata key -> model field, since two of the keys are not valid
# identifiers. test_protocol_fields_match_the_parser guards against drift.
PROTOCOL_FIELDS: Final[dict[str, str]] = {
    "bacnet": "bacnet",
    "dnp3": "dnp3",
    "dnp3-serial": "dnp3_serial",
    "modbus": "modbus",
    "sunspec": "sunspec",
    "iec60870-5-104": "iec104",
}


@dataclass(frozen=True)
class Problem:
    """One thing wrong with the scenario.

    Attributes:
        hostname: Host it belongs to, or None for whole-scenario problems.
        message: What is wrong, naming the metadata field where relevant.
        hint: Optional second line -- valid values, what was found instead.
        fatal: True if this would prevent the experiment being built.
    """

    hostname: str | None
    message: str
    hint: str = ""
    fatal: bool = True


def closest(name: str, candidates: Iterable[str]) -> str:
    """Suggest a near-miss for a bad reference, else list what is available."""

    candidates = sorted(candidates)
    if not candidates:
        return "no candidates are defined in this scenario"
    close = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    if close:
        return f"did you mean '{close[0]}'?"
    return "known: " + ", ".join(candidates)


class Interface(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = "?"
    address: str = ""
    vlan: str = ""
    type: str = "ethernet"


class Network(BaseModel):
    model_config = ConfigDict(extra="allow")

    interfaces: list[Interface] = []


class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    network: Network = Network()


class Device(BaseModel):
    """One entry in a protocol's device list.

    Its identity, plus the optional per-device register overrides that replace
    the infrastructure's default fields. Anything else is dropped by
    SceptreMetadataParser, so it is rejected here rather than silently ignored.
    An inverter's overrides are SunSpec model numbers, hence the ints.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str
    name: str
    analog_read: list[str | int] | None = Field(None, alias="analog-read")
    analog_read_write: list[str | int] | None = Field(None, alias="analog-read-write")
    binary_read: list[str | int] | None = Field(None, alias="binary-read")
    binary_read_write: list[str | int] | None = Field(None, alias="binary-read-write")


class Meta(BaseModel):
    """Base for every host's metadata; extra keys are the norm, so they stay."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Most checks read the host's interfaces, so a host with no usable topology
    # node is skipped: the missing node is reported once instead of cascading.
    needs_topology: ClassVar[bool] = True

    type: str | None = None
    labels: list[str] | str | None = None
    helics: dict[str, Any] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        """Append this host's problems. Never raises -- see the module docstring."""

        broker = (self.helics or {}).get("broker")
        if broker and broker not in ctx["hostnames"]:
            host.flag(
                ctx,
                f"metadata.helics.broker '{broker}' matches no host",
                closest(broker, ctx["hostnames"]),
            )


class ProviderMeta(Meta):
    simulator: str = ""
    case: str | None = None
    oneline: str | None = None
    solver: str | None = None
    publish_points: str | None = None
    simulation_file: str | None = None
    gt: str | None = None
    gt_template: str | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        if not self.simulator:
            host.flag(
                ctx,
                "metadata.simulator is not set; the default config is used",
                fatal=False,
            )
            return

        required = simulators.REQUIRED_METADATA.get(Simulator.parse(self.simulator), ())
        for key in required:
            if getattr(self, key) is None:
                host.flag(
                    ctx,
                    f"metadata.{key} is required when simulator is '{self.simulator}'",
                )

        if self.gt and not self.gt_template:
            host.flag(ctx, "metadata.gt_template is required when metadata.gt is set")


class FdServerMeta(Meta):
    # A fep's devices can come entirely from the RTUs it adopts.
    requires_protocol: ClassVar[bool] = True

    provider: str
    infrastructure: str
    server_hostname: str | None = None
    bacnet: list[Device] | None = None
    dnp3: list[Device] | None = None
    dnp3_serial: list[Device] | None = Field(None, alias="dnp3-serial")
    modbus: list[Device] | None = None
    sunspec: list[Device] | None = None
    iec104: list[Device] | None = Field(None, alias="iec60870-5-104")

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        if self.provider not in ctx["providers"]:
            host.flag(
                ctx,
                f"metadata.provider '{self.provider}' matches no provider host",
                closest(self.provider, ctx["providers"]),
            )

        infrastructure = self.infrastructure.lower().strip()
        if infrastructure not in INFRASTRUCTURE_NAMES:
            host.flag(
                ctx,
                f"metadata.infrastructure '{self.infrastructure}' is not supported",
                "supported: " + ", ".join(INFRASTRUCTURE_NAMES),
            )
        else:
            self._check_device_types(host, ctx, infrastructure)

        server = self.server_hostname
        if server and server not in ctx["hostnames"]:
            host.flag(
                ctx,
                f"metadata.server_hostname '{server}' matches no host",
                closest(server, ctx["hostnames"]),
            )

        if self.requires_protocol and all(
            getattr(self, f) is None for f in PROTOCOL_FIELDS.values()
        ):
            host.flag(
                ctx,
                "declares no protocol; this device will expose nothing",
                "expected one of: " + ", ".join(PROTOCOL_FIELDS),
                fatal=False,
            )

        if not non_mgmt(host, case_sensitive=False):
            host.flag(
                ctx,
                "no non-mgmt interface; this device will bind to an empty address",
                describe_interfaces(host),
                fatal=False,
            )

    def _check_device_types(
        self, host: "Host", ctx: Context, infrastructure: str
    ) -> None:
        """Every device type must be one this infrastructure has."""

        valid = INFRASTRUCTURES[infrastructure]["devices"]
        for key, field in PROTOCOL_FIELDS.items():
            for index, device in enumerate(getattr(self, field) or []):
                if device.type.lower().strip() not in valid:
                    host.flag(
                        ctx,
                        f"metadata.{key}[{index}] type '{device.type}' is not "
                        f"valid for {infrastructure}",
                        "valid: " + ", ".join(sorted(valid)),
                    )


class FdClientMeta(Meta):
    connected_rtus: list[str] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        if not non_mgmt(host, case_sensitive=False):
            host.flag(
                ctx,
                "fd-client needs a non-mgmt, non-serial interface to bind to",
                describe_interfaces(host),
            )
        host.flag_refs(ctx, "connected_rtus", self.connected_rtus, "fd_servers")


class FepMeta(FdServerMeta):
    """A fep is an fd-server that also fronts the fd-servers it adopts."""

    requires_protocol: ClassVar[bool] = False

    connected_rtus: list[str] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        host.flag_refs(ctx, "connected_rtus", self.connected_rtus, "fd_servers")


class OpcMeta(Meta):
    connected_rtus: list[str] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        if not non_mgmt(host):
            host.flag(
                ctx,
                'OPC needs an interface on a vlan other than "mgmt"',
                describe_interfaces(host)
                + '; note this check is case-sensitive, "MGMT" does not count',
            )
        host.flag_refs(ctx, "connected_rtus", self.connected_rtus, "fd_servers")


class ScadaMeta(Meta):
    project: str | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        # A supplied project skips the autoproject path, and with it these.
        if self.project:
            return
        if not non_mgmt(host):
            host.flag(
                ctx,
                'scada-server needs an interface on a vlan other than "mgmt"',
                describe_interfaces(host),
            )


class HmiMeta(Meta):
    connected_scadas: list[str] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        host.flag_refs(ctx, "connected_scadas", self.connected_scadas, "scadas")


class EngineerMeta(Meta):
    connected_rtus: list[str] | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        host.flag_refs(ctx, "connected_rtus", self.connected_rtus, "fd_servers")


class HistorianMeta(Meta):
    primary: str | None = None

    def check(self, host: "Host", ctx: Context) -> None:
        super().check(host, ctx)

        if not non_mgmt(host):
            host.flag(
                ctx,
                'historian needs an interface on a vlan other than "mgmt"',
                describe_interfaces(host),
            )
        if self.primary and self.primary not in ctx["hostnames"]:
            host.flag(
                ctx,
                f"metadata.primary '{self.primary}' matches no host",
                closest(self.primary, ctx["hostnames"]),
                fatal=False,
            )


# metadata.type -> model. Anything else (a HELICS broker, an ELK box, a host
# with no type at all) gets the base Meta and its checks.
KINDS: Final[dict[str, type]] = {
    "provider": ProviderMeta,
    "fd-server": FdServerMeta,
    "fd-client": FdClientMeta,
    "fep": FepMeta,
    "opc": OpcMeta,
    "scada-server": ScadaMeta,
    "hmi": HmiMeta,
    "engineer-workstation": EngineerMeta,
    "historian": HistorianMeta,
}

# What each reference key has to name, for the flag_refs message.
REFERENTS: Final[dict[str, str]] = {
    "fd_servers": "a known fd-server",
    "scadas": "a known scada-server",
}


def _kind(metadata: Any) -> str:
    kind = metadata.get("type") if isinstance(metadata, dict) else metadata.type
    return kind if kind in KINDS else "other"


Metadata = Annotated[
    Annotated[ProviderMeta, Tag("provider")]
    | Annotated[FdServerMeta, Tag("fd-server")]
    | Annotated[FdClientMeta, Tag("fd-client")]
    | Annotated[FepMeta, Tag("fep")]
    | Annotated[OpcMeta, Tag("opc")]
    | Annotated[ScadaMeta, Tag("scada-server")]
    | Annotated[HmiMeta, Tag("hmi")]
    | Annotated[EngineerMeta, Tag("engineer-workstation")]
    | Annotated[HistorianMeta, Tag("historian")]
    | Annotated[Meta, Tag("other")],
    Discriminator(_kind),
]


class Host(BaseModel):
    """One host from the app's host list, merged with its topology node."""

    model_config = ConfigDict(extra="ignore")

    hostname: str
    topology: TopologyNode | None = None
    metadata: Metadata = Meta()

    def flag(
        self, ctx: Context, message: str, hint: str = "", *, fatal: bool = True
    ) -> None:
        ctx["problems"].append(Problem(self.hostname, message, hint, fatal))

    def flag_refs(
        self, ctx: Context, key: str, names: list[str] | None, referent: str
    ) -> None:
        """Flag reference-list entries that name no host of the right kind."""

        valid = ctx[referent]
        for name in names or []:
            if name not in valid:
                self.flag(
                    ctx,
                    f"metadata.{key} references '{name}', which is not "
                    f"{REFERENTS[referent]}",
                    closest(name, valid),
                    fatal=False,
                )

    @model_validator(mode="after")
    def _check(self, info: ValidationInfo) -> "Host":
        """Topology first: every other check dereferences it."""

        usable = bool(self.topology and self.topology.network.interfaces)
        if self.topology is None:
            self.flag(
                info.context,
                "listed in the sceptre app but missing from the topology",
                "add a topology node with this hostname, or remove the host",
            )
        elif not usable:
            self.flag(
                info.context,
                "topology node has no network interfaces",
                "the app reads interfaces[0] for this host's address",
            )

        if usable or not self.metadata.needs_topology:
            self.metadata.check(self, info.context)
        return self


class Scenario(BaseModel):
    """Every host, plus the checks that span all of them.

    These run only once every host has parsed.
    """

    hosts: list[Host]

    @model_validator(mode="after")
    def _check(self, info: ValidationInfo) -> "Scenario":
        ctx = info.context

        if not any(h.metadata.type == "provider" for h in self.hosts):
            ctx["problems"].append(
                Problem(
                    None,
                    "no provider is defined; a SCEPTRE experiment needs at least one",
                    'add a host with metadata.type "provider"',
                )
            )

        elks = sorted(h.hostname for h in self.hosts if h.metadata.type == "elk")
        if len(elks) > 1:
            ctx["problems"].append(
                Problem(
                    None,
                    f"{len(elks)} ELK boxes defined; only one is supported",
                    "found: " + ", ".join(elks),
                )
            )

        # The autoproject path needs a primary OPC to point the SCADA server at.
        if not any(
            h.metadata.type == "opc" and not is_backup(h.hostname) and non_mgmt(h)
            for h in self.hosts
            if h.topology
        ):
            for host in self.hosts:
                if isinstance(host.metadata, ScadaMeta) and not host.metadata.project:
                    host.flag(
                        ctx,
                        "no primary OPC for this scada-server to connect to",
                        'every OPC host is named "*secondary*" or "*bak*", which the '
                        "app treats as a backup; at least one must be a primary",
                    )
        return self


# Malformed input never reaches check(); pydantic rejects it first. These turn
# its errors into the same wording as everything else.
_MALFORMED: Final[dict[str, str]] = {
    "list_type": "must be a list",
    "dict_type": "must be a mapping with 'type' and 'name'",
    "model_type": "must be a mapping with 'type' and 'name'",
    "string_type": "must be a string",
}

_EXTRA_KEY_HINT: Final[str] = "supported keys: " + ", ".join(DEVICE_KEYS)


def _path(loc: Iterable[str | int]) -> str:
    """Render an error location as a metadata path: metadata.dnp3[0].name."""

    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def _malformed(err: dict[str, Any], host: dict[str, Any]) -> Problem:
    """Turn one pydantic error into a Problem, in the app's own wording."""

    loc = list(err["loc"])[2:]  # drop ("hosts", index)
    if len(loc) > 1 and loc[0] == "metadata" and loc[1] in KINDS:
        del loc[1]  # drop the discriminator tag
    kind = host["metadata"].get("type") or "host"
    found = type(err.get("input")).__name__

    if err["type"] == "missing":
        if len(loc) > 1 and isinstance(loc[-2], int):
            return Problem(
                host["hostname"], f"{_path(loc[:-1])} is missing '{loc[-1]}'"
            )
        return Problem(host["hostname"], f"{_path(loc)} is required on {kind} hosts")

    if err["type"] == "extra_forbidden":
        return Problem(
            host["hostname"],
            f"{_path(loc[:-1])} has unsupported key(s): {loc[-1]}",
            _EXTRA_KEY_HINT,
        )

    if err["type"] in _MALFORMED:
        hint = ""
        if err["type"] == "list_type" and found == "str":
            hint = f"write it as a list, e.g. {loc[-1]}: [{err['input']}]"
        return Problem(
            host["hostname"],
            f"{_path(loc)} {_MALFORMED[err['type']]}, got {found}",
            hint,
        )

    return Problem(host["hostname"], f"{_path(loc)}: {err['msg']}")


def validate(app: "Sceptre") -> list[Problem]:
    """Every problem in the scenario, fatal first, then by hostname."""

    def plain(value: Any) -> dict[str, Any]:
        return value.to_dict() if hasattr(value, "to_dict") else dict(value or {})

    hosts = [
        {
            "hostname": h.hostname,
            "metadata": plain(h.get("metadata")),
            "topology": plain(h.topology) if h.get("topology") else None,
        }
        for h in app.extract_all_nodes()
    ]

    def named(kind: str) -> set[str]:
        return {h["hostname"] for h in hosts if h["metadata"].get("type") == kind}

    problems: list[Problem] = []
    context = {
        "problems": problems,
        "hostnames": {h["hostname"] for h in hosts},
        "providers": named("provider"),
        "fd_servers": named("fd-server"),
        "scadas": named("scada-server"),
    }

    try:
        Scenario.model_validate({"hosts": hosts}, context=context)
    except ValidationError as exc:
        problems += [_malformed(err, hosts[err["loc"][1]]) for err in exc.errors()]

    return sorted(problems, key=lambda p: (not p.fatal, p.hostname or ""))


def report(problems: list[Problem]) -> str:
    """Render problems as a single readable block, fatal ones first."""

    fatal = [p for p in problems if p.fatal]
    warnings = [p for p in problems if not p.fatal]
    width = max((len(p.hostname or "scenario") for p in problems), default=0)

    def block(items: list[Problem], heading: str) -> list[str]:
        lines = ["", heading]
        for problem in items:
            who = (problem.hostname or "scenario").ljust(width)
            lines.append(f"  {who}  {problem.message}")
            if problem.hint:
                lines.append(f"  {' ' * width}  -> {problem.hint}")
        return lines

    counts = []
    if fatal:
        counts.append(f"{len(fatal)} error{'s' if len(fatal) != 1 else ''}")
    if warnings:
        counts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")

    out = [f"sceptre scenario check: {' and '.join(counts)}"]
    if fatal:
        out += block(fatal, "ERRORS (the experiment cannot be built):")
    if warnings:
        out += block(warnings, "WARNINGS (accepted, but probably not intended):")
    return "\n".join(out)


def enforce(app: "Sceptre") -> None:
    """Log the report, then raise AppError if anything fatal was found.

    Logged before the raise so it lands as its own record, not as an exception
    message inside a traceback.
    """

    problems = validate(app)
    if not problems:
        return

    text = report(problems)
    fatal = [p for p in problems if p.fatal]
    if not fatal:
        logger.warning(text)
        return

    logger.error(text)
    raise error.AppError(
        f"sceptre scenario check failed: {len(fatal)} "
        f"error{'s' if len(fatal) != 1 else ''}; see the report above"
    )
