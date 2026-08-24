"""Pre-start for the three field device types.

They share the metadata parsing and the interface selection that decides what a
device binds to, and a fep adopts the configs its fd-servers built.
"""

from typing import Final

from phenix_apps.apps.sceptre.configs import configs
from phenix_apps.apps.sceptre.hosts import address, interfaces, mgmt
from phenix_apps.apps.sceptre.metadata import (
    DEFAULT_PUBLISH_ENDPOINT,
    SceptreMetadataParser,
    Simulator,
    server_endpoint,
)
from phenix_apps.apps.sceptre.stages import PreStartState
from phenix_apps.common import error
from phenix_apps.common.logger import logger

# Protocol metadata key -> the port the field device serves it on.
PORTS: Final[dict[str, str]] = {
    "dnp3": "20000-local",
    "dnp3-serial": "20000-local",
    "modbus": "502-local",
    "modbus-serial": "502-local",
    "bacnet": "47808-local",
    "goose": "61850",
    "iec60870-5-104": "2404-local",
    "sunspec": "502-local",
}

# Reported as 0 when unused: dashboards expect the key to exist.
ALWAYS_REPORTED: Final[tuple[str, ...]] = (
    "20000-local",
    "502-local",
    "47808-local",
    "2404-local",
)


class FieldDevices(PreStartState):
    """fd-server, fd-client and fep handling."""

    def fd_servers(self) -> None:
        """Build a FieldDeviceConfig per fd-server and render its config + startup script.

        Reads: provider_map
        Writes: fd_server_configs, fdlist, power_object_list, reg_config
        """

        self.fd_server_configs = {}
        self.fdlist = {}
        self.power_object_list = []
        self.reg_config = {}

        needrestart = bool(self.hosts("ignition"))

        for fd_counter, fd_ in enumerate(self.hosts("fd-server"), start=1):
            if not fd_.metadata:
                logger.warning(f"No metadata for fd-server '{fd_.hostname}'")
                continue

            provider = self.provider_map[fd_.metadata.provider]
            pub_endpoint = provider.metadata.get(
                "publish_endpoint", DEFAULT_PUBLISH_ENDPOINT
            )

            try:
                srv_name = fd_.metadata.get("server_hostname", None)
                fd_logic = fd_.metadata.get("logic", None)
                fd_cycle_time = fd_.metadata.get("cycle_time", None)
                subtype = fd_.metadata.get("subtype", "single")
                parsed = SceptreMetadataParser(fd_.metadata)

                simulator = provider.metadata.get("simulator", "")
                if simulator in (
                    Simulator.POWER_WORLD,
                    Simulator.POWER_WORLD_HELICS,
                    Simulator.POWER_WORLD_DYNAMICS,
                    Simulator.PYPOWER,
                ):
                    self.power_object_list.extend(
                        device["name"]
                        for devices in parsed.devices_by_protocol.values()
                        for device in devices
                    )
            except Exception as e:
                msg = f"There was a problem parsing metadata for '{fd_.hostname}'.\nPROBLEM: {e}"
                logger.error(msg)
                raise error.AppError(msg) from None

            fd_directory = self.host_dir(fd_.hostname)

            # metadata.server_hostname overrides the provider as the state source.
            server = self.app.extract_node(srv_name) if srv_name else provider
            srv_endpoint = server_endpoint(address(server))

            # sort out experiment vs serial interface
            ifaces = interfaces(fd_)
            fd_interfaces = {}

            for interface in ifaces:
                if fd_interfaces.get("tcp", ""):
                    break
                if not interface.type == "serial" and (
                    interface.vlan and interface.vlan.lower() != "mgmt"
                ):
                    fd_interfaces["tcp"] = interface.address
                elif len(ifaces) == 2 and interface.type == "serial":
                    fd_interfaces["tcp"] = interface.address
                # hack for siren. please direct all objections to this hack to /dev/null
                elif simulator == Simulator.SIREN and not interface.type == "serial":
                    fd_interfaces["tcp"] = interface.address

            # the provider publish_endpoint should look like 'udp://*;127.0.0.1:40000',
            # but the rtu needs to bind specifically to the mgmt interface
            if mgmt_ifaces := mgmt(fd_):
                pub_endpoint = pub_endpoint.replace("*", mgmt_ifaces[0].address)

            if serial_interfaces := [x.device for x in ifaces if x.type == "serial"]:
                fd_interfaces["serial"] = serial_interfaces

            InfrastructureFieldDeviceConfig = configs.get_fdconfig_class(
                fd_.metadata.infrastructure
            )

            fd_config = InfrastructureFieldDeviceConfig(
                provider=fd_.metadata.provider,
                name=fd_.hostname,
                interfaces=fd_interfaces,
                devices_by_protocol=parsed.devices_by_protocol,
                publish_endpoint=pub_endpoint,
                server_endpoint=srv_endpoint,
                device_subtype=subtype,
                reg_config=self.reg_config,
                counter=fd_counter,
            )

            self.fd_server_configs[fd_.hostname] = fd_config

            config_file = fd_directory / "config.xml"

            sceptre_type = "field-device"
            if "sunspec" in parsed.devices_by_protocol:
                sceptre_type = "sunspec"

            if sceptre_type == "sunspec":
                self.render(
                    "sunspec.mako",
                    config_file,
                    name=fd_config.name,
                    cycle_time=fd_cycle_time,
                    infra=fd_config.infrastructure_name,
                    device=fd_config.protocols[0].devices[0],
                    ipaddr=fd_config.ipaddr,
                    publish_endpoint=fd_config.publish_endpoint,
                    server_endpoint=fd_config.server_endpoint,
                    devname=fd_config.protocols[0].devices[0].registers[0].devname,
                )
            else:
                self.render(
                    "fd_server.mako",
                    config_file,
                    fd_config=fd_config,
                    logic=fd_logic,
                    cycle_time=fd_cycle_time,
                )

            self.app.render_sceptre_start(
                fd_, name=sceptre_type, needrestart=needrestart
            )

            # What the ELK dashboards read: which ports this device listens on.
            ports = {PORTS[key]: 1 for key in fd_.metadata if key in PORTS}
            ports["9990-remote"] = len(ports)
            for port in ALWAYS_REPORTED:
                ports.setdefault(port, 0)
            self.fdlist[fd_.hostname] = ports

    def fd_clients(self) -> None:
        """Render each fd-client's config and startup script.

        Reads: fd_server_configs
        """

        fd_clients = self.hosts("fd-client")

        for fd_ in fd_clients:
            if not fd_.metadata:
                logger.warning(
                    f"No metadata for fd-client '{fd_.hostname}', skipping..."
                )
                continue

            fd_directory = self.host_dir(fd_.hostname)

            ifaces = interfaces(fd_)

            for iface in ifaces:
                if not iface.type == "serial" and (
                    iface.vlan and iface.vlan.lower() != "mgmt"
                ):
                    fd_ip = iface.address
                    break

                if len(ifaces) == 2 and iface.type == "serial":
                    fd_ip = iface.address

            server_configs = [
                self.fd_server_configs[server]
                for server in fd_.metadata.get("connected_rtus", [])
                if server in self.fd_server_configs
            ]

            self.render(
                "fd_client.mako",
                fd_directory / "config.xml",
                server_configs=server_configs,
                command_endpoint=fd_ip,
                name=fd_.hostname,
            )

            self.app.render_sceptre_start(fd_, name="field-device")

    def feps(self) -> None:
        """Render each fep's config and startup script.

        A fep adopts the devices of the fd-servers in connected_rtus and pops them
        out of self.fd_server_configs, so OPC and ELK see the fep, not the RTUs.

        Reads: fd_server_configs, provider_map, reg_config
        Writes: fd_server_configs
        """

        for fep_counter, fd_ in enumerate(self.hosts("fep"), start=1):
            if not fd_.metadata:
                msg = f"No metadata for {fd_.hostname}."
                logger.warning(msg)
                continue

            fd_directory = self.host_dir(fd_.hostname)

            parsed = SceptreMetadataParser(fd_.metadata)
            provider = self.provider_map[parsed.provider_name]
            pub_endpoint = provider.metadata.get(
                "publish_endpoint", DEFAULT_PUBLISH_ENDPOINT
            )

            ifaces = interfaces(fd_)
            fd_interfaces = {}

            for iface in ifaces:
                if "upstream" in iface.name.lower():
                    fd_interfaces["tcp"] = iface.address
                    break

                if not iface.type == "serial" and (
                    iface.vlan and iface.vlan.lower() != "mgmt"
                ):
                    fd_interfaces["tcp"] = iface.address
                elif len(ifaces) == 2 and iface.type == "serial":
                    if not fd_interfaces.get("tcp", ""):
                        fd_interfaces["tcp"] = iface.address

            # Falls back to the address the fep binds to when there is no mgmt
            # interface; these used to be left unbound.
            cmd_ip = fd_interfaces.get("tcp", "")
            srv_endpoint = f"tcp://{cmd_ip}:1330"

            # the provider publish_endpoint should look like 'udp://*;127.0.0.1:40000',
            # but the rtu needs to bind specifically to the mgmt interface
            if mgmt_ifaces := mgmt(fd_):
                cmd_ip = mgmt_ifaces[0].address
                pub_endpoint = pub_endpoint.replace("*", cmd_ip)
                srv_endpoint = f"tcp://{cmd_ip}:1330"

            if serial_interfaces := [x.device for x in ifaces if x.type == "serial"]:
                fd_interfaces["serial"] = serial_interfaces

            server_configs = []
            for server in fd_.metadata.get("connected_rtus", []):
                if server not in self.fd_server_configs:
                    continue
                server_configs.append(self.fd_server_configs[server])

                # the fep exposes the devices of every RTU it adopts
                for protocol in self.fd_server_configs[server].protocols:
                    parsed.devices_by_protocol.setdefault(protocol.protocol, []).extend(
                        {"type": device.device_type, "name": device.device_name}
                        for device in protocol.devices
                    )

                # excludes them from the OPC config and upstream data
                self.fd_server_configs.pop(server, "")

            InfrastructureFieldDeviceConfig = configs.get_fdconfig_class(
                fd_.metadata.infrastructure
            )

            fep_config = InfrastructureFieldDeviceConfig(
                provider=fd_.metadata.provider,
                name=fd_.hostname,
                interfaces=fd_interfaces,
                devices_by_protocol=parsed.devices_by_protocol,
                publish_endpoint=pub_endpoint,
                server_endpoint=srv_endpoint,
                device_subtype=fd_.metadata.get("subtype", "single"),
                reg_config=self.reg_config,
                counter=fep_counter,
            )
            self.fd_server_configs[fep_config.name] = fep_config

            self.render(
                "fep_template.mako",
                fd_directory / "config.xml",
                server_configs=server_configs,
                command_endpoint=cmd_ip,
                name=fd_.hostname,
                fep_config=fep_config,
            )

            self.app.render_sceptre_start(fd_, name="field-device")
