"""The pre-start stage: generate the files configure() promised to inject.

Unlike configure, the order in steps() is load-bearing -- each method documents
what it reads and writes of the state declared in PreStartState.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from phenix_apps.apps.sceptre import simulators
from phenix_apps.apps.sceptre.configs.configs import all_registers
from phenix_apps.apps.sceptre.field_devices import FieldDevices
from phenix_apps.apps.sceptre.hosts import address, os_type
from phenix_apps.apps.sceptre.metadata import (
    DEFAULT_PUBLISH_ENDPOINT,
    Simulator,
    server_endpoint,
)
from phenix_apps.apps.sceptre.scada import Scada
from phenix_apps.apps.sceptre.stages import Stage, Steps
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

if TYPE_CHECKING:
    from phenix_apps.apps.sceptre.configs.registers import Register


def value_type(register: "Register") -> str:
    """How HELICS types a register's value."""

    return "bool" if register.fieldtype.split("-")[0] == "binary" else "double"


def unique(values: Iterable[str]) -> list[str]:
    """Sorted, with duplicates removed."""

    return sorted(dict.fromkeys(values))


# Register types a HELICS federate subscribes to rather than publishes.
INPUT_REGISTERS: Final[tuple[str, ...]] = (
    "analog-input",
    "binary-input",
    "input-register",
    "discrete-input",
)


def timing_config(helics_md: dict) -> dict:
    """The optional HELICS timing keys, normalised for the template."""

    config = {}
    if "request_time" in helics_md:
        config["request_time"] = (
            '"max"' if helics_md["request_time"] == "max" else helics_md["request_time"]
        )
    if "period" in helics_md:
        config["period"] = helics_md["period"]
    if "real_time" in helics_md:
        config["real_time"] = "true" if helics_md["real_time"] else "false"
    if "end_time" in helics_md:
        config["end_time"] = helics_md["end_time"]
    return config


def joined(entry: dict, *keys: str) -> str:
    """The entry's values for these keys, comma-joined; absent keys are dropped."""

    return ",".join(str(entry[key]) for key in keys if key in entry)


def extra_topics(helics_md: dict) -> tuple[list[str], list[str], list[str]]:
    """Additional pubs/subs/ends declared by hand in the metadata."""

    pubs = [joined(p, "key", "type") for p in helics_md.get("publications", [])]
    subs = [
        joined(s, "key", "type", "info") for s in helics_md.get("subscriptions", [])
    ]
    ends = [joined(e, "name", "destination") for e in helics_md.get("endpoints", [])]
    return pubs, subs, ends


class PreStart(FieldDevices, Scada, Stage):
    """Every pre-start handler, in dependency order.

    The field device and SCADA clusters live in their own modules; what is left
    here is the provider, HELICS and ELK work, plus the order everything runs in.
    """

    def steps(self) -> Steps:
        return (
            # First: builds provider_map, which every field device needs to
            # resolve its own provider's endpoints.
            ("provider", self.provider_configs),
            # fd_servers fills fd_server_configs, which HELICS, fd-client, ELK
            # and OPC all read; feps then adopts some of those RTUs and pops
            # them back out, so it must finish before ELK and OPC run.
            ("fd-server", self.fd_servers),
            # Needs the object list fd_servers accumulates.
            ("power objects", self.power_objects),
            ("helics federate", self.helics_federates),
            ("fd-client", self.fd_clients),
            ("fep", self.feps),
            ("elk", self.elk_files),
            # collect_ips before the rest: opc, hmi and engineer workstation
            # read the scada/historian IPs it gathers. opc then builds the
            # OpcConfigs that scada server and historian look up.
            ("collect ips", self.collect_ips),
            ("opc", self.opcs),
            ("scada server", self.scada_servers),
            ("hmi", self.hmis),
            ("engineer wkst", self.engineer_workstations),
            ("historian", self.historians),
        )

    def provider_configs(self) -> None:
        """Render each provider's config.ini and startup script.

        Writes: hil_object_list, objects_file_path, provider_hosts, provider_map
        """

        self.provider_hosts = self.hosts("provider")
        self.provider_map = {}
        self.objects_file_path = None

        # an ignition hmi needs the provider to sleep first
        needsleep = bool(self.labelled("ignition"))

        for provider in self.provider_hosts:
            if "metadata" not in provider:
                logger.warning(
                    f"No metadata for provider '{provider.hostname}', skipping..."
                )
                continue

            self.provider_map[provider.hostname] = provider
            pub_endpoint = provider.metadata.get(
                "publish_endpoint", DEFAULT_PUBLISH_ENDPOINT
            )
            ipv4_address = address(provider)
            srv_endpoint = server_endpoint(ipv4_address)

            self.app.render_sceptre_start(
                provider,
                server_endpoint=srv_endpoint,
                publish_endpoint=pub_endpoint,
                needsleep=needsleep,
            )

            simulator = provider.metadata.get("simulator", "")
            if not simulator:
                logger.warning(
                    f"No simulator specified for provider '{provider.hostname}'"
                )

            provider_directory = self.host_dir(provider.hostname)

            kwargs: simulators.ProviderConfig = {
                "solver": simulator,
                "debug": str(provider.metadata.get("debug", False)).capitalize(),
                "server_endpoint": srv_endpoint,
                "publish_endpoint": pub_endpoint,
            }

            sim = Simulator.parse(simulator)

            if sim in simulators.POWER_WORLD_FAMILY:
                kwargs |= simulators.power_world_kwargs(
                    self, provider, provider_directory
                )
            if sim in simulators.HELICS_FAMILY:
                kwargs |= simulators.helics_kwargs(os_type(provider) == "linux")

            if sim == Simulator.POWER_WORLD_DYNAMICS:
                kwargs |= simulators.power_world_dynamics_kwargs(provider)
            elif sim == Simulator.PYPOWER:
                kwargs |= simulators.pypower_kwargs(provider)
            elif sim in simulators.YAML_CONFIGURED:
                kwargs |= simulators.yaml_config_kwargs(
                    self, provider, sim, provider_directory, ipv4_address
                )

            # TODO: only render this when there is no override file?
            self.render(
                "provider_config.mako",
                provider_directory / "config.ini",
                **kwargs,
            )

    def power_objects(self) -> None:
        """Write the combined power object list for a PowerWorld provider.

        Reads: hil_object_list, objects_file_path, power_object_list
        Writes: power_object_list
        """

        if self.objects_file_path:
            self.power_object_list = unique(
                self.power_object_list + self.hil_object_list
            )
            Path(self.objects_file_path).write_text("\n".join(self.power_object_list))

    def register_topics(self, name: str, helics_provider: bool) -> dict:
        """subs/pubs/ends derived from every field device register.

        The Helics provider federate subscribes to every input register; any
        other federate publishes the registers its own provider serves.

        Reads: fd_server_configs
        """

        registers = list(all_registers(self.fd_server_configs))

        if helics_provider:
            return {
                # <provider>/<tag>,<type> for every input register
                "subs": unique(
                    f"{c.provider}/{r.devname}.{r.field},{value_type(r)}"
                    for c, _, r in registers
                    if r.regtype in INPUT_REGISTERS
                ),
                "pubs": [],
                # <tag>,<provider>/<tag>
                "ends": unique(
                    f"{r.devname}.{r.field},{c.provider}/{r.devname}.{r.field}"
                    for c, _, r in registers
                ),
            }

        mine = [(c, r) for c, _, r in registers if c.provider == name]
        return {
            "subs": [],
            # <tag>,<type>
            "pubs": unique(f"{r.devname}.{r.field},{value_type(r)}" for _, r in mine),
            # <tag>
            "ends": unique(f"{r.devname}.{r.field}" for _, r in mine),
        }

    def helics_federates(self) -> None:
        """Render each HELICS federate's helics.json.

        Reads: fd_server_configs
        """

        for fed in self.labelled("helics-federate"):
            helics_md = fed.metadata.get("helics", {})
            # If broker isn't specified in metadata, assume it's local
            broker = helics_md.get("broker", None)  # should be hostname
            broker = self.app.extract_node(broker) if broker else fed.topology

            config = {
                "name": helics_md.get("name", fed.hostname),
                "broker_address": address(broker),
                "log_level": helics_md.get("log_level", 3),  # 3 = summary
            }
            config.update(timing_config(helics_md))
            config.update(
                self.register_topics(
                    config["name"], fed.metadata.get("simulator", None) == "Helics"
                )
            )

            # any additional pubs/subs/ends (e.g. new sub for interdependency logic)
            pubs, subs, ends = extra_topics(helics_md)
            config["pubs"] += pubs
            config["subs"] += subs
            config["ends"] += ends

            # remove any empty config keys
            config = {k: v for k, v in config.items() if v}

            self.render(
                "helics_config.mako",
                self.host_dir(fed.hostname) / "helics.json",
                config=config,
            )

    def elk_files(self) -> None:
        """Write fdlist.json, reg_addrs.json and the provider restart script.

        Reads: fd_server_configs, fdlist, provider_hosts
        """

        fdlist_file = self.elk_dir / "fdlist.json"
        fdlist_file.write_text(json.dumps(self.fdlist))
        utils.mark_executable(fdlist_file)

        # One restart script, not one per provider: the old loop rendered the
        # same file for each provider and the last one's address won.
        if self.provider_hosts:
            provider_restart_file = self.elk_dir / "sceptre_provider_restart.py"
            self.render(
                "elk.mako",
                provider_restart_file,
                ip=address(self.provider_hosts[-1]),
            )
            utils.mark_executable(provider_restart_file)

        gtmap = [
            {
                "ip": config.ipaddr,
                "register_type": register.regtype,
                "address": register.addr,
                "name": register.devname,
                "field": register.field,
            }
            for config, protocol, register in all_registers(self.fd_server_configs)
            if "modbus" in protocol.protocol
        ]

        (self.elk_dir / "reg_addrs.json").write_text(json.dumps(gtmap))
