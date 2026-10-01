import ipaddress as ipaddr
from pathlib import Path

from phenix_apps.apps import AppBase
from phenix_apps.common import settings, utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger


class Caldera(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        self.app_dir: Path = Path(self.exp_dir) / "caldera"
        self.app_dir.mkdir(parents=True, exist_ok=True)

        self.files_dir: Path = (
            Path(settings.PHENIX_DIR) / "images" / self.exp_name / "caldera"
        )
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def configure(self):
        logger.info(f"Configuring user app: {self.name}")

        md = self.metadata

        for idx, server in enumerate(md.get("servers", [])):
            hostname = utils.validate_hostname(server.get("hostname", f"caldera-{idx}"))

            node = {
                "type": "VirtualMachine",
                "general": {
                    "hostname": hostname,
                    "vm_type": "kvm",
                },
                "hardware": {
                    "os_type": "linux",
                    "vcpus": server.get("cpu", 2),
                    "memory": server.get("memory", 8192),
                    "drives": [
                        {"image": server.get("image", "caldera.qc2")},
                    ],
                },
                "network": {"interfaces": []},
            }

            for idx, iface in enumerate(server.interfaces):
                ip = ipaddr.ip_interface(iface.address)

                interface = {
                    "name": f"IF{idx}",
                    "type": "ethernet",
                    "proto": "static",
                    "address": str(ip.ip),
                    "mask": ip.network.prefixlen,
                    "gateway": iface.gateway,
                    "vlan": iface.vlan,
                }

                node["network"]["interfaces"].append(interface)

            self.add_node(node)

        logger.info(f"Configured user app: {self.name}")

    def pre_start(self):
        logger.info(f"Starting user application: {self.name}")

        templates = utils.abs_path(__file__, "templates/")
        md = self.metadata

        for idx, server in enumerate(md.get("servers", [])):
            hostname = utils.validate_hostname(server.get("hostname", f"caldera-{idx}"))

            node = self.extract_node(hostname)
            addr = node.network.interfaces[0].address

            for fact in server.get("facts", []):
                inject = {
                    "src": fact,
                    "dst": f"/opt/caldera/data/sources/{Path(fact).name}",
                }

                self.add_inject(hostname, inject)

            for adversary in server.get("adversaries", []):
                inject = {
                    "src": adversary,
                    "dst": f"/opt/caldera/data/adversaries/{Path(adversary).name}",
                }

                self.add_inject(hostname, inject)

            if server.get("config"):
                config_file = server.get("config")
            else:
                config_file = utils.safe_join(self.app_dir, f"{hostname}-config.yml")

                with config_file.open("w") as f:
                    utils.mako_serve_template("default_config.mako", templates, f)

            inject = {
                "src": str(config_file),
                "dst": "/opt/caldera/conf/default.yml",
            }

            self.add_inject(hostname, inject)

            firefox_bookmark_config_file = utils.safe_join(
                self.app_dir, f"{hostname}-firefox-policies.json"
            )

            with firefox_bookmark_config_file.open("w") as f:
                utils.mako_serve_template(
                    "firefox_bookmark.mako", templates, f, addr=addr
                )

            inject = {
                "src": str(firefox_bookmark_config_file),
                "dst": "/etc/firefox/policies/policies.json",
            }

            self.add_inject(hostname, inject)

            firefox_autostart_config_file = utils.safe_join(
                self.app_dir, f"{hostname}-firefox-autostart.json"
            )

            with firefox_autostart_config_file.open("w") as f:
                utils.mako_serve_template(
                    "firefox_autostart.mako", templates, f, addr=addr
                )

            inject = {
                "src": str(firefox_autostart_config_file),
                "dst": "/root/.config/autostart/Caldera.desktop",
            }

            self.add_inject(hostname, inject)

        hosts = self.extract_all_nodes(False)

        for host in hosts:
            utils.validate_hostname(host.hostname)

            try:
                addr = ipaddr.ip_address(host.metadata.server)
            except ValueError:
                tokens = host.metadata.server.split(":")
                server = tokens[0]

                if len(tokens) == 1:
                    iface = 0
                else:
                    iface = int(tokens[1])

                node = self.extract_node(server)
                addr = node.network.interfaces[iface].address

            if host.topology.hardware.os_type == "windows":
                if not (Path(templates) / "windows_agent.mako").exists():
                    raise AppError(
                        f"cannot generate sandcat agent for Windows host "
                        f"'{host.hostname}': windows_agent.mako template is missing "
                        f"from {templates}"
                    )

                agent_file = utils.safe_join(
                    self.app_dir, f"{host.hostname}-sandcat-agent.ps1"
                )

                with agent_file.open("w") as f:
                    utils.mako_serve_template(
                        "windows_agent.mako", templates, f, addr=addr
                    )

                self.add_inject(
                    hostname=host.hostname,
                    inject={
                        "src": str(agent_file),
                        "dst": "/phenix/startup/90-sandcat-agent.ps1",
                    },
                )
            elif host.topology.hardware.os_type == "linux":
                agent_file = utils.safe_join(
                    self.app_dir, f"{host.hostname}-sandcat-agent.sh"
                )

                with agent_file.open("w") as f:
                    utils.mako_serve_template(
                        "linux_agent.mako", templates, f, addr=addr
                    )

                self.add_inject(
                    hostname=host.hostname,
                    inject={
                        "src": str(agent_file),
                        "dst": "/etc/phenix/startup/90-sandcat-agent.sh",
                    },
                )

        logger.info(f"Started user application: {self.name}")
