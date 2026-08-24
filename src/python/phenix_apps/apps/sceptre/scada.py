"""Pre-start for the SCADA side: OPC, SCADA server, HMI, engineer, historian.

They share the OPC lookup: each host is configured against the OPC on its own
subnet, and the config objects pass down the chain from opcs() onward.
"""

import shutil
from pathlib import Path

from phenix_apps.apps.sceptre.configs import configs
from phenix_apps.apps.sceptre.hosts import address, is_backup, non_mgmt, same_subnet
from phenix_apps.apps.sceptre.stages import PreStartState
from phenix_apps.common.logger import logger


def opc_on_subnet(
    ip: str, *config_maps: dict[str, configs.OpcConfig]
) -> tuple[str, configs.OpcConfig | None]:
    """(opc ip, OpcConfig) for the OPC on ip's subnet, else ("", None)."""

    for configs_by_ip in config_maps:
        for opc_ip, config in configs_by_ip.items():
            if same_subnet(ip, opc_ip):
                return opc_ip, config
    return "", None


class Scada(PreStartState):
    """OPC, SCADA server, HMI, engineer workstation and historian handling."""

    def collect_ips(self) -> None:
        """Collect the non-mgmt IPs that the OPC, HMI and engineer handlers need.

        Writes: historian_hosts, historian_ips, scada_hosts, scada_ips
        """

        self.scada_hosts = self.hosts("scada-server")
        self.historian_hosts = self.hosts("historian")

        self.historian_ips = [
            i.address for h in self.historian_hosts for i in non_mgmt(h)
        ]
        self.scada_ips = [i.address for s in self.scada_hosts for i in non_mgmt(s)]

    def opcs(self) -> None:
        """Build an OpcConfig per OPC and render its config + TopServer script.

        Reads: fd_server_configs, historian_ips, scada_ips
        Writes: opc_bak_configs, opc_configs
        """

        # Keyed by OPC IP: historians use the one on their own subnet.
        self.opc_configs = {}
        self.opc_bak_configs = {}
        opcs = self.hosts("opc")

        for opc in opcs:
            rtus = opc.metadata.get("connected_rtus") if opc.metadata else None
            if rtus is None:
                logger.warning(
                    f"No rtus defined for {opc.hostname}. It will be configured to monitor all field devices"
                )
                opc_fd_configs = self.fd_server_configs
            else:
                opc_fd_configs = {
                    rtu: self.fd_server_configs[rtu]
                    for rtu in rtus
                    if rtu in self.fd_server_configs
                }

            opc_directory = self.host_dir(opc.hostname)

            primary_opc = False
            opc_ip = non_mgmt(opc)[0].address
            opc_config = configs.OpcConfig(opc_fd_configs, opc_ip)
            if not is_backup(opc.hostname):
                self.opc_configs[opc_ip] = opc_config
                primary_opc = True
            # Backups, for scada server/historian automation.
            else:
                self.opc_bak_configs[opc_ip] = opc_config

            self.render(
                "opc_template.mako",
                opc_directory / "opc.xml",
                opc_config=opc_config,
            )

            self.render(
                "topserver.mako",
                opc_directory / "topserver.ps1",
                scada_ips=self.scada_ips,
                historian_ips=self.historian_ips,
                opc_ip=opc_ip,
                primary_opc=primary_opc,
            )

    def scada_servers(self) -> None:
        """Render the SCADA project files and startup script.

        Reads: opc_bak_configs, opc_configs, scada_hosts
        """

        for scada_server in self.scada_hosts:
            scada_directory = self.host_dir(scada_server.hostname)

            if "project" in scada_server.metadata:
                self.render("scada.mako", scada_directory / "scada.ps1")
            else:
                # The OPC on this server's own subnet, else a backup, else the first.
                scada_ip = non_mgmt(scada_server)[0].address
                opc_ip, opc_config = opc_on_subnet(
                    scada_ip, self.opc_configs, self.opc_bak_configs
                )

                if opc_ip == "":
                    logger.warning(
                        f"{scada_server.hostname}: no OPC server on subnet "
                        f"{scada_ip}; falling back to {next(iter(self.opc_configs))}"
                    )
                    opc_ip = next(iter(self.opc_configs))
                    opc_config = self.opc_configs[opc_ip]

                shutil.copytree(
                    Path(self.app.templates_dir) / "mydesigner",
                    scada_directory / "autoproject",
                    dirs_exist_ok=True,
                )
                self.render(
                    "scada_connectionsdef.mako",
                    scada_directory / "autoproject" / "connectionsdef.json",
                    opc_ip=opc_ip,
                )

                self.render(
                    "scada_table.mako",
                    scada_directory / "autoproject" / "Table.svg",
                    opc_config=opc_config,
                )

                self.render(
                    "scada_autoproject.mako", scada_directory / "scada_autoproject.ps1"
                )

    def hmis(self) -> None:
        """Render each HMI's startup script.

        Reads: scada_hosts, scada_ips
        """

        hmis = self.hosts("hmi")
        by_hostname = {s.hostname: s for s in self.scada_hosts}

        for hmi in hmis:
            hmi_ip = address(hmi)
            # named scada servers, else whatever is on this HMI's subnet
            if "connected_scadas" in hmi.metadata:
                hmi_scada_ips = [
                    address(by_hostname[name])
                    for name in hmi.metadata.connected_scadas
                    if name in by_hostname
                ]
            elif len(self.scada_ips) == 1:
                hmi_scada_ips = self.scada_ips
            else:
                hmi_scada_ips = [
                    scada_ip
                    for scada_ip in self.scada_ips
                    if same_subnet(scada_ip, hmi_ip)
                ]

            hmi_directory = self.host_dir(hmi.hostname)

            self.render(
                "hmi.mako",
                hmi_directory / "hmi.ps1",
                scada_ips=hmi_scada_ips,
                hmi_ip=hmi_ip,
            )

    def engineer_workstations(self) -> None:
        """Render the PuTTY and auto-connect scripts.

        The workstation connects to field devices, not to the SCADA server.
        """

        rtus = self.hosts("fd-server")
        engineer_workstations = self.hosts("engineer-workstation")
        by_hostname = {rtu.hostname: rtu for rtu in rtus}

        for engineer_workstation in engineer_workstations:
            # connected_rtus, or every fd-server when it is not set
            if "connected_rtus" in engineer_workstation.metadata:
                eng_fd = [
                    by_hostname[name]
                    for name in engineer_workstation.metadata.connected_rtus
                    if name in by_hostname
                ]
            else:
                eng_fd = list(rtus)

            engineer_directory = self.host_dir(engineer_workstation.hostname)

            self.render(
                "putty.mako",
                engineer_directory / "putty.ps1",
                eng_fd=eng_fd,
            )

            if "connect_interval" in engineer_workstation.metadata:
                self.render(
                    "auto_winscp.mako",
                    engineer_directory / "auto_winscp.ps1",
                    eng_fd=eng_fd,
                    connect_interval=engineer_workstation.metadata.connect_interval,
                )

    def historians(self) -> None:
        """Render each historian's config and startup script.

        Reads: historian_hosts, opc_configs
        """

        secondary_historian_ips: dict[str, list[str]] = {"historian": []}

        for historian in self.historian_hosts:
            iface = non_mgmt(historian)[0]

            # No metadata at all makes a host a secondary of "historian".
            primary = (
                historian.metadata.get("primary") if historian.metadata else "historian"
            )
            if primary:
                secondary_historian_ips.setdefault(primary, []).append(iface.address)

        for historian in self.historian_hosts:
            historian_directory = self.host_dir(historian.hostname)
            hist_ip = non_mgmt(historian)[0].address

            # The OPC on this historian's own subnet, if there is one. Without it
            # the historian has no address to collect from, so it gets no tags
            # either -- it used to inherit whichever config the OPC and SCADA loops
            # left behind, and silently list another OPC's devices.
            opc_config_ip, opc_config = opc_on_subnet(hist_ip, self.opc_configs)
            if not opc_config_ip:
                logger.warning(
                    f"{historian.hostname}: no OPC server on subnet {hist_ip}; "
                    "its historian config will have no tags"
                )

            # Backups replicate from the primary, so an empty config is enough.
            hist_config = configs.HistorianConfig()

            if not is_backup(historian.hostname):
                secondary_ips = secondary_historian_ips.get(historian.hostname, [])
                metadata = historian.metadata or {}
                # Field "types" to store; empty means every field OPC provides.
                hist_fields = metadata.get("fields", [])

                if metadata.get("connecttoscada"):
                    hist_config = configs.HistorianConfig(
                        None, "", secondary_ips, True, hist_fields
                    )
                else:
                    hist_config = configs.HistorianConfig(
                        opc_config, opc_config_ip, secondary_ips, False, hist_fields
                    )

            self.render(
                "historian_config.mako",
                historian_directory / "historian_config.txt",
                hist_config=hist_config,
                hist_name=historian.hostname,
            )

            self.render(
                "historian.mako",
                historian_directory / "historian.ps1",
                hist_config=hist_config,
                historian_name=historian.hostname.upper(),
            )
