import io
import ipaddress as ip
import os
import sys
from importlib.metadata import entry_points
from typing import Any

import minimega
from rich import box as rich_box
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from phenix_apps.apps import AppBase
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.registry import PLUGIN_REGISTRY, get_plugin
from phenix_apps.common import settings, utils
from phenix_apps.common.logger import logger


class Scale(AppBase):
    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)

        # Setup standard directories for the scale app
        self.app_dir: str = f"{self.exp_dir}/{self.name}"
        os.makedirs(self.app_dir, exist_ok=True)

        self.files_dir: str
        if self.dryrun:
            self.files_dir = f"/tmp/phenix/images/{self.exp_name}"
        else:
            self.files_dir = f"{settings.PHENIX_DIR}/images/{self.exp_name}"

        os.makedirs(self.files_dir, exist_ok=True)

        # Load all available plugins
        self._discover_plugins()

    def _get_plugin_name(self, profile: dict[str, Any]) -> str:
        plugin_spec = profile.get("plugin", "builtin")
        if isinstance(plugin_spec, dict):
            return plugin_spec.get("name", "builtin")
        return plugin_spec

    def _get_required_plugins(self) -> set[str]:
        plugins = set()
        for p in self.get_profiles():
            plugins.add(self._get_plugin_name(p))
        return plugins

    def _discover_plugins(self) -> None:
        # Discover plugins via specific group
        try:
            logger.debug(
                "Discovering plugins via 'phenix.scale.plugins' entry points..."
            )
            eps = entry_points(group="phenix.scale.plugins")
            for ep in eps:
                try:
                    ep.load()
                    logger.debug(f"Loaded plugin from entry point: {ep.name}")
                except Exception as e:
                    logger.error(f"Failed to load plugin {ep.name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to discover plugins via entry_points: {e}")

    def _get_plugin_instance(self, profile: dict[str, Any]) -> ScalePlugin:
        """Dynamically loads the plugin specified in profile (default: builtin)."""
        name = self._get_plugin_name(profile)
        plugin_spec = profile.get("plugin", "builtin")
        version = (
            plugin_spec.get("version", "latest")
            if isinstance(plugin_spec, dict)
            else "latest"
        )

        try:
            instance = get_plugin(name, version)
            logger.debug(
                f"Loaded plugin instance: {instance.__class__.__name__} (requested: {version})"
            )
            return instance
        except ValueError as e:
            logger.error(
                f"Failed to load scale plugin '{name}': {e}. Available: {list(PLUGIN_REGISTRY.keys())}",
            )
            sys.exit(1)

    def get_profiles(self) -> list[dict[str, Any]]:
        if "profiles" in self.metadata:
            profiles = self.metadata["profiles"]
            for profile in profiles:
                if "name" not in profile:
                    profile["name"] = self._get_plugin_name(profile)
            return profiles

        # Backward compatibility: treat root metadata as a single default profile
        profile = (
            self.metadata.to_dict()
            if hasattr(self.metadata, "to_dict")
            else dict(self.metadata)
        )
        profile["name"] = "default"
        return [profile]

    def configure(self) -> None:
        """Delegate configure stage to plugins for each profile."""
        profiles = self.get_profiles()
        logger.info(f"Configuring user app: {self.name} with {len(profiles)} profiles")

        summary_headers = ["Profile", "Hostname", "Containers"]
        summary_rows = []

        for profile in profiles:
            plugin = self._get_plugin_instance(profile)
            p_name = profile.get("name", "unknown")
            p_plugin = self._get_plugin_name(profile)
            logger.info(f"Processing profile '{p_name}' with plugin '{p_plugin}'")

            plugin.validate_profile(self, profile)
            plugin.pre_configure(self, profile)

            config_dump = plugin.get_plugin_config()
            if config_dump:
                logger.debug(f"Plugin '{p_plugin}' configuration: {config_dump}")

            node_count = plugin.get_node_count()
            logger.info(f"Profile '{p_name}': Scaling {node_count} nodes.")

            for i in range(1, node_count + 1):
                spec = plugin.get_node_spec(i)
                self._apply_node_defaults(spec, profile)

                # Ensure hostname is present in the spec
                if "hostname" not in spec["general"]:
                    spec["general"]["hostname"] = plugin.get_hostname(i)

                self.add_node(spec)

                hostname = spec["general"]["hostname"]
                self._configure_node_common(plugin, i, hostname, profile)
                plugin.on_node_configured(self, i, hostname)
                containers = plugin.get_container_count(i)
                summary_rows.append([p_name, hostname, containers])

        self._print_summary_table(summary_headers, summary_rows)
        logger.info(f"Configured user app: {self.name} with {len(profiles)} profiles")

    def _configure_node_common(
        self, plugin: ScalePlugin, index: int, hostname: str, profile: dict[str, Any]
    ) -> None:
        """Adds standard startup script and injections."""
        startup_config = f"{self.app_dir}/{hostname}-startup.sh"
        mm_dir = f"/tmp/miniccc/files/{self.exp_name}"
        mm_file = f"{mm_dir}/{hostname}.mm"

        additional_cmds = plugin.get_additional_startup_commands(index, hostname)

        startup_script_content = f"""echo 'STARTING...'
{additional_cmds or ""}
while [ ! -S /tmp/minimega/minimega ]; do sleep 1; done
while [ ! -f {mm_file} ]; do sleep 1; done
ovs-vsctl add-br {self.exp_name}
ovs-vsctl add-port {self.exp_name} ens1
mm read {mm_file}
echo 'DONE!'
"""

        with open(startup_config, "w") as f:
            f.write(startup_script_content)

        self.add_inject(
            hostname=hostname,
            inject={
                "src": startup_config,
                "dst": "/etc/phenix/startup/999-scale.sh",
            },
        )

        # Add user-defined start scripts
        start_scripts = profile.get("start_scripts", [])
        for idx, script in enumerate(start_scripts):
            self.add_inject(
                hostname=hostname,
                inject={
                    "src": script,
                    "dst": f"/etc/phenix/startup/{501 + idx}-script.sh",
                },
            )

    def _apply_node_defaults(
        self, spec: dict[str, Any], profile: dict[str, Any]
    ) -> None:
        # Global defaults
        defaults = {"cpu": 1, "memory": 512, "image": "minimeta.qc2"}

        node_tmpl = profile.get("node_template", {})

        # Ensure structure
        if "type" not in spec:
            spec["type"] = "VirtualMachine"
        if "general" not in spec:
            spec["general"] = {}
        if "vm_type" not in spec["general"]:
            spec["general"]["vm_type"] = "kvm"
        if "hardware" not in spec:
            spec["hardware"] = {}
        if "network" not in spec:
            spec["network"] = {"interfaces": []}

        # Apply node_template network override if present
        if "network" in node_tmpl:
            spec["network"] = node_tmpl["network"]

        # Add default interface if none provided
        if not spec["network"].get("interfaces"):
            spec["network"]["interfaces"] = [
                {
                    "name": "ens1",
                    "type": "ethernet",
                    "proto": "manual",
                    "vlan": "0",  # causes all VLANs to be trunked into VM
                }
            ]

        hw = spec["hardware"]

        # 1. Apply node_template overrides (highest priority for user settings)
        if "cpu" in node_tmpl:
            hw["vcpus"] = node_tmpl["cpu"]
        if "memory" in node_tmpl:
            hw["memory"] = node_tmpl["memory"]
        if "image" in node_tmpl:
            # Handle image location (hw['image'] vs hw['drives'])
            if hw.get("drives"):
                hw["drives"][0]["image"] = node_tmpl["image"]
            else:
                # If image was set as string in hw
                if "image" in hw:
                    del hw["image"]
                hw["drives"] = [{"image": node_tmpl["image"]}]

        # 2. Apply global defaults if still missing (lowest priority)
        if "vcpus" not in hw:
            hw["vcpus"] = defaults["cpu"]
        if "memory" not in hw:
            hw["memory"] = defaults["memory"]
        if "os_type" not in hw:
            hw["os_type"] = "linux"

        if "drives" not in hw and "image" not in hw:
            hw["drives"] = [{"image": defaults["image"]}]

    def post_start(self) -> None:
        """Delegate post-start stage to plugins for each profile."""
        profiles = self.get_profiles()
        logger.info(
            f"Running post-start for user app: {self.name} with {len(profiles)} profiles",
        )

        if not self.dryrun:
            # minimega.connect prints to stdout on version mismatch, which corrupts JSON output
            with open(os.devnull, "w") as devnull:
                old_stdout = sys.stdout
                sys.stdout = devnull
                try:
                    mm = minimega.connect(namespace=self.exp_name)
                finally:
                    sys.stdout = old_stdout

        summary_headers = [
            "Profile",
            "Hostname",
            "Containers",
            "Filesystem",
            "Networks",
        ]
        summary_rows = []

        # Use stderr for progress to avoid interfering with stdout JSON output if any
        with Progress(console=Console(stderr=True)) as progress:
            for profile in profiles:
                plugin = self._get_plugin_instance(profile)
                plugin.pre_post_start(self, profile)

                # Process networks per profile
                container_tmpl = profile.get("container_template", {})
                net_info = self._process_networks(container_tmpl.get("networks", []))
                gateway = self._get_gateway(container_tmpl.get("gateway"))
                filesystem = container_tmpl.get("rootfs", "otsimfs.tgz")

                node_count = plugin.get_node_count()
                task = progress.add_task(
                    f"[cyan]Profile {profile.get('name', 'unknown')}", total=node_count
                )

                for i in range(1, node_count + 1):
                    hostname = plugin.get_hostname(i)
                    containers = plugin.get_container_count(i)

                    # Capture IP info for summary
                    network_summary = []
                    raw_networks = container_tmpl.get("networks", [])
                    if net_info and raw_networks:
                        for idx, net in enumerate(net_info[1]):
                            net_name = raw_networks[idx].get("name", "unknown")
                            start_ip = net["addr"]
                            if containers > 0:
                                end_ip = start_ip + containers - 1
                                network_summary.append(
                                    f"{net_name}: {start_ip}-{end_ip}"
                                )
                            else:
                                network_summary.append(f"{net_name}: N/A")

                    summary_rows.append(
                        [
                            profile.get("name", "unknown"),
                            hostname,
                            containers,
                            filesystem,
                            ", ".join(network_summary),
                        ]
                    )

                    mm_config = f"{self.files_dir}/{hostname}.mm"

                    cfg = {
                        "NAMESPACE": self.name,
                        "QUEUEING": True,
                        "START_INDEX": 1,
                        "HOSTNAME": hostname,
                        "COUNT": containers,
                        "FILESYSTEM": filesystem,
                        "NET_STR": net_info[0] if net_info else "",
                        "NETS": net_info[1] if net_info else [],
                        "GATEWAY": gateway,
                        "UPDATE_HOSTS": "dns" in profile.get("aws", {}),
                        "VCPU": container_tmpl.get("cpu", 1),
                        "MEMORY": container_tmpl.get("memory", 512),
                    }

                    plugin.update_template_config(cfg)

                    template_name = plugin.get_template_name()
                    # Check if the plugin has its own templates_dir, otherwise use the app's default
                    plugin_templates_dir = getattr(
                        plugin, "templates_dir", self.templates_dir
                    )

                    with open(mm_config, "w") as file_:
                        utils.mako_serve_template(
                            template_name, plugin_templates_dir, file_, config=cfg
                        )

                    if not self.dryrun:
                        mm.cc_filter(filter=f"name={hostname}")
                        mm.cc_send(mm_config)

                    # Increase all nets' starting IP for next loop
                    if net_info:
                        for net in net_info[1]:
                            net["addr"] += containers

                    progress.update(task, advance=1)

        self._print_summary_table(summary_headers, summary_rows)
        logger.info(
            f"Ran post-start for user app: {self.name} with {len(profiles)} profiles",
        )

    def _print_summary_table(self, headers: list[str], rows: list[list[Any]]) -> None:
        if not rows:
            return

        # Group by first column (Profile)
        formatted_rows = []
        last_profile = None
        for row in rows:
            current_row = list(row)
            if current_row[0] == last_profile:
                current_row[0] = ""
            else:
                last_profile = current_row[0]
            formatted_rows.append(current_row)

        # Calculate totals
        total_nodes = 0
        total_containers = 0

        # Find indices for summing
        node_idx = headers.index("Nodes") if "Nodes" in headers else -1
        container_idx = headers.index("Containers") if "Containers" in headers else -1

        for row in rows:
            if node_idx != -1:
                total_nodes += int(row[node_idx])
            if container_idx != -1:
                total_containers += int(row[container_idx])

        plugin_str = ", ".join(sorted(self._get_required_plugins()))

        title = f"Scale App Summary ({plugin_str}) - {len(rows)} Nodes ({len(self.get_profiles())} Profiles):"

        # Styles
        if self.dryrun:
            title_style = "bold magenta"
            header_style = "bold blue"
            border_style = "blue"
            row_style = "green"
        else:
            title_style = "bold"
            header_style = "bold cyan"
            border_style = "white"
            row_style = None

        table = Table(
            title=title,
            title_style=title_style,
            header_style=header_style,
            border_style=border_style,
            box=rich_box.SIMPLE,
            show_footer=True,
        )

        for i, h in enumerate(headers):
            footer = ""
            if i == 0:
                footer = "Total"
            elif i == node_idx:
                footer = str(total_nodes)
            elif i == container_idx:
                footer = str(total_containers)

            justify = "right" if i in [node_idx, container_idx] else "left"
            table.add_column(h, footer=footer, justify=justify)

        for row in formatted_rows:
            row = [str(v) for v in row]
            if row_style:
                table.add_row(*row, style=row_style)
            else:
                table.add_row(*row)

        if self.dryrun:
            console = Console(stderr=True)
            console.print()
            console.print(table)
        else:
            console = Console(file=io.StringIO(), force_terminal=False, width=120)
            console.print(table)
            logger.info(f"\n{console.file.getvalue()}")

    def _process_networks(
        self, networks: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]] | None:
        """Parses network metadata."""
        if not networks:
            if self.dryrun:
                # Return mock network data for dry-run
                return (
                    "phenix,100 phenix,101",
                    [
                        {"addr": ip.IPv4Address("172.16.0.1"), "prefix": 24},
                        {"addr": ip.IPv4Address("10.0.0.1"), "prefix": 24},
                    ],
                )
            return None

        nets = []
        net_str = ""
        for net in networks:
            net_dict = {}
            try:
                vlan_id = getattr(self.experiment.status.vlans, net["name"])
                net_str += f"{self.exp_name},{vlan_id} "
            except (AttributeError, KeyError):
                if self.dryrun:
                    # Mock VLAN ID for dry-run if not found
                    net_str += f"{self.exp_name},100 "
                    net_iface = ip.IPv4Interface(net["network"])
                    net_dict["addr"] = net_iface.ip
                    net_dict["prefix"] = net_iface.network.prefixlen
                    nets.append(net_dict)
                    continue
                logger.warning(f"VLAN not found: {net['name']}")
                continue

            net_iface = ip.IPv4Interface(net["network"])
            net_dict["addr"] = net_iface.ip
            net_dict["prefix"] = net_iface.network.prefixlen
            nets.append(net_dict)
        return (net_str.strip(), nets)

    def _get_gateway(self, gateway: str | None) -> str | None:
        """Resolves the gateway IP from metadata."""
        if not gateway:
            return None

        try:
            # Assume gateway defined as IP address
            return str(ip.ip_address(gateway))
        except ValueError:
            # Assume gateway defined as tapped VLAN name
            if not self.dryrun:
                try:
                    getattr(self.experiment.status.vlans, gateway)
                except (AttributeError, KeyError):
                    logger.error(
                        f"Gateway VLAN '{gateway}' not found in experiment status"
                    )
                    return None

            tap_app = self.extract_app("tap")
            if not tap_app:
                if self.dryrun:
                    return "192.168.1.1"
                logger.error("Tap app not found! Required for gateway resolution.")
                return None

            for tap in tap_app.metadata.get("taps", []):
                if tap.get("vlan") == gateway:
                    return str(ip.IPv4Interface(tap.ip).ip)

            logger.error("VLAN specified for gateway is not tapped")
            return None
