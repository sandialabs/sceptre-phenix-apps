import copy
import ipaddress
import math
import os
import shutil
import sys
import tarfile
from typing import Any, ClassVar

import lxml.etree as ET
from box import Box
from pydantic import BaseModel, Field, model_validator

from phenix_apps.apps import AppBase
from phenix_apps.apps.otsim.config import Config
from phenix_apps.apps.otsim.device import Register
from phenix_apps.apps.otsim.logic import Logic
from phenix_apps.apps.otsim.nodered import NodeRed
from phenix_apps.apps.otsim.protocols.dnp3 import DNP3
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.registry import register_plugin
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class WindTurbineConfig(BaseModel):
    name: str = "wind-turbine"
    count: int = Field(default=1, ge=1)
    containers_per_node: int = 6
    node_template: dict[str, Any] = Field(default_factory=dict)
    container_template: dict[str, Any] = Field(default_factory=dict)
    templates: dict[str, Any] = Field(default_factory=dict)
    ground_truth: dict[str, Any] = Field(
        default_factory=dict, alias="ground-truth-module"
    )
    helics: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    ext_net: dict[str, Any] | None = None

    model_config = {"extra": "ignore", "validate_assignment": True}

    @model_validator(mode="after")
    def validate_logic(self) -> "WindTurbineConfig":
        ext_net_config = self.container_template.get("external_network", {})
        if isinstance(ext_net_config, list) and ext_net_config:
            object.__setattr__(self, "ext_net", ext_net_config[0])
        else:
            object.__setattr__(self, "ext_net", ext_net_config)

        if self.count > 0 and not self.ext_net:
            raise ValueError(
                "external_network must be defined in container_template when count > 0"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


@register_plugin("wind_turbine")
class WindTurbine(ScalePlugin):
    """
    Wind Turbine Plugin for Scale App.

    This domain-specific plugin simulates a wind farm by deploying multiple wind turbine assets.
    Each turbine consists of 6 containers (Main Controller, Anemometer, Yaw, 3x Blades)
    connected via a private network.

    The plugin calculates the number of VMs required to host the requested number of turbines
    based on the `containers_per_node` density setting.

    See `phenix_apps/apps/scale/plugins/wind_turbine.md` for full documentation.
    """

    # Defines the components of a single wind turbine, their private IPs, and their order.
    COMPONENTS: ClassVar[list[dict[str, str]]] = [
        {"name": "main-controller", "ip": "10.135.1.254/24"},
        {"name": "signal-converter", "ip": "10.135.1.21/24"},
        {"name": "yaw-controller", "ip": "10.135.1.11/24"},
        {"name": "blade-1", "ip": "10.135.1.31/24"},
        {"name": "blade-2", "ip": "10.135.1.32/24"},
        {"name": "blade-3", "ip": "10.135.1.33/24"},
    ]

    def __init__(self) -> None:
        # Set the template directory for this plugin
        py_path = sys.modules[self.__class__.__module__].__file__
        self.templates_dir: str = utils.abs_path(py_path, "templates")
        self.brokers: dict[str, dict[str, Any]] = {}

    def _resolve_ext_start_ip(self) -> ipaddress.IPv4Address:
        """Resolve the base IP for the external network, ignoring app.py increments."""
        if self.config.ext_net.get("start_ip"):
            return ipaddress.IPv4Address(self.config.ext_net["start_ip"])
        if self.config.ext_net.get("network"):
            iface = ipaddress.IPv4Interface(self.config.ext_net["network"])
            # If the IP is the network address (e.g. 192.168.1.0/24), start at .1
            if iface.ip == iface.network.network_address:
                return iface.ip + 1
            return iface.ip

        return ipaddress.IPv4Address("192.168.100.1")  # type: ignore

    def _process_helics_broker_metadata(self, md: dict[str, Any]) -> str | None:
        if "broker" in md:
            broker = md["broker"]
            if "hostname" in broker:
                if "|" in broker["hostname"]:
                    hostname, iface = broker["hostname"].split("|", 1)
                else:
                    hostname = broker["hostname"]
                    iface = None

                if "base-fed-count" in broker:
                    if hostname not in self.brokers:
                        self.brokers[hostname] = {
                            "feds": int(broker["base-fed-count"]),
                            "log-level": broker.get("log-level", "SUMMARY"),
                            "log-file": broker.get(
                                "log-file", "/var/log/helics-broker.log"
                            ),
                        }
                    self.brokers[hostname]["feds"] += 1

                node = self.app.extract_node(hostname)
                assert node, f"HELICS broker host '{hostname}' not found in topology"

                addr = None
                if iface:
                    for i in node.network.interfaces:
                        if i["name"] == iface and "address" in i:
                            addr = i["address"]
                            break
                elif node.network.interfaces:
                    addr = node.network.interfaces[0].get("address")
                assert addr, (
                    f"Could not resolve IP for HELICS broker on host '{hostname}'"
                )
                return addr
            if "address" in broker:
                return broker["address"]
        return None

    def _get_container_details(self, index: int) -> list[dict[str, Any]]:
        """
        Helper to generate configuration details for all containers on a specific node.
        Returns a list of dictionaries containing hostname, type, networks, IPs, etc.
        """
        containers = self.get_container_count(index)
        if containers == 0:
            return []

        start_container_idx = (index - 1) * self.config.containers_per_node
        ext_start_ip = self._resolve_ext_start_ip()

        # Resolve external network details from profile
        ext_net_str = ""
        ext_prefix = 24
        gateway = None

        ext_net = self.config.ext_net

        # Use app._process_networks to resolve VLANs and prefixes
        if ext_net:
            res = self.app._process_networks([ext_net])
            if res:
                ext_net_str = res[0]
                if res[1]:
                    ext_prefix = res[1][0]["prefix"]

            gateway = self.app._get_gateway(ext_net.get("gateway"))

        # Static map of private IPs for XML generation
        component_ips = {
            "main": self.COMPONENTS[0]["ip"].split("/")[0],
            "anemo": self.COMPONENTS[1]["ip"].split("/")[0],
            "yaw": self.COMPONENTS[2]["ip"].split("/")[0],
            "blade1": self.COMPONENTS[3]["ip"].split("/")[0],
            "blade2": self.COMPONENTS[4]["ip"].split("/")[0],
            "blade3": self.COMPONENTS[5]["ip"].split("/")[0],
        }

        details = []
        for i in range(containers):
            global_idx = start_container_idx + i
            turbine_idx = global_idx // 6
            comp_idx = global_idx % 6
            component_info = self.COMPONENTS[comp_idx]
            comp_type = component_info["name"]
            turbine_num = turbine_idx + 1

            item = {
                "hostname": f"wtg-{turbine_num}-{comp_type}",
                "type": comp_type,
                "turbine_num": turbine_num,
                "component_ips": component_ips,
                "turbine_net": f"wtg-{turbine_num}",
                "private_ip_cidr": component_info["ip"],
                "private_gateway": self.COMPONENTS[0]["ip"].split("/")[0],
            }

            if comp_type == "main-controller":
                # Main controller gets external net AND turbine net (2 interfaces)
                if ext_net_str:
                    item["networks"] = f"{ext_net_str} {item['turbine_net']}"
                else:
                    item["networks"] = item["turbine_net"]

                # Calculate External IP
                ext_ip = ext_start_ip + turbine_num - 1

                # IPs: [External, Private]
                item["ips"] = [f"{ext_ip}/{ext_prefix}", item["private_ip_cidr"]]
                item["gateway"] = gateway
                item["topology_ip"] = str(ext_ip)
            else:
                # Others just get turbine net (1 interface)
                item["networks"] = item["turbine_net"]
                item["ips"] = [item["private_ip_cidr"]]
                item["gateway"] = item["private_gateway"]
                item["topology_ip"] = item["private_ip_cidr"].split("/")[0]

            details.append(item)

        return details

    def pre_configure(self, app: AppBase, profile: dict[str, Any]) -> None:
        self.app = app
        self.config = WindTurbineConfig(**profile)

        # Default labels
        labels = {"infra": "wind"}
        labels.update(self.config.labels)

        # Default node specification
        self.base_spec = {
            "type": "VirtualMachine",
            "general": {
                "hostname": "wind-turbine",
                "vm_type": "kvm",
            },
            "hardware": {
                "os_type": "linux",
                "vcpus": self.config.node_template.get("cpu", 8),
                "memory": self.config.node_template.get("memory", 16384),
            },
            "labels": labels,
        }

        logger.debug(f"WindTurbine plugin configured for {self.config.count} nodes.")

    def get_node_count(self) -> int:
        # Total containers = turbines * 6 components
        total_containers = self.config.count * 6
        if self.config.containers_per_node > 0:
            return math.ceil(total_containers / self.config.containers_per_node)
        return self.config.count

    def get_node_spec(self, index: int) -> dict[str, Any]:
        spec = copy.deepcopy(self.base_spec)
        spec["general"]["hostname"] = self.get_hostname(index)
        return spec

    def get_hostname(self, index: int) -> str:
        return f"{self.config.name}-{index}"

    def on_node_configured(self, app: AppBase, index: int, hostname: str) -> None:
        self.app = app  # Ensure app reference is fresh
        self.brokers = {}  # Reset broker counts for each new VM
        container_details = self._get_container_details(index)

        # Inject weather data if configured
        anemo_tmpl = self.config.templates.get("default", {}).get("anemometer", {})
        weather = anemo_tmpl.get("weather", {})
        src_data = weather.get("replayData")

        if src_data:
            self.app.add_inject(
                hostname=hostname,
                inject={"src": src_data, "dst": "/scale/shared/weather.csv"},
            )

        for i, d in enumerate(container_details):
            cnt_num = i + 1
            comp_type = d["type"]
            turbine_num = d["turbine_num"]
            ips = d["component_ips"]

            # Prepare directory
            cfg_dir = f"{self.app.app_dir}/{hostname}/{cnt_num}"
            os.makedirs(cfg_dir, exist_ok=True)

            # Generate Config
            # The otsim.Config class expects the raw app metadata structure.
            # We construct a dictionary that mimics it.
            otsim_md = {"ground-truth-module": self.config.ground_truth}
            config = Config(otsim_md)
            # Mock node metadata structure expected by otsim classes
            node_meta = {
                "hostname": d["hostname"],
                "metadata": {
                    "type": comp_type,
                    "template": "default",
                    "ground-truth-module": copy.deepcopy(self.config.ground_truth),
                },
                "topology": {
                    "network": {"interfaces": [{"address": d["topology_ip"]}]}
                },
            }
            # Inject turbine ID/Name into ground truth labels if needed
            gt = node_meta["metadata"]["ground-truth-module"]
            if "elastic" in gt and "labels" in gt["elastic"]:
                replacements = {
                    "{{turbine_name}}": f"wtg-{turbine_num}",
                    "{{turbine_id}}": str(turbine_num),
                }
                for name, value in gt["elastic"]["labels"].items():
                    for key, val in replacements.items():
                        value = value.replace(key, val)
                    gt["elastic"]["labels"][name] = value

            config.init_xml_root(node_meta["metadata"])

            logs = ET.Element("logs")
            file = ET.Element(
                "file",
                {
                    "size": "5",
                    "backups": "1",
                    "age": "1",
                    "compress": "true",
                },
            )
            file.text = "/etc/ot-sim/log.txt"
            logs.append(file)
            config.append_to_cpu(logs)

            if comp_type == "main-controller":
                self._generate_main_controller(
                    config, node_meta, ips, turbine_num, cfg_dir
                )
            elif comp_type == "signal-converter":
                self._generate_anemometer(config, node_meta)
            elif comp_type == "yaw-controller":
                self._generate_yaw_controller(config, node_meta)
            elif comp_type.startswith("blade"):
                self._generate_blade_controller(config, node_meta)

            # Write config
            config.to_file(f"{cfg_dir}/config.xml")

        # Create tarball of configs
        tgz_path = f"{self.app.exp_dir}/wind-configs.tgz"
        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(self.app.app_dir, arcname=os.path.basename(self.app.app_dir))

        # Inject tarball
        self.app.add_inject(
            hostname=hostname,
            inject={
                "src": tgz_path,
                "dst": "/wind-configs.tgz",
            },
        )

        # Add HELICS annotations if brokers were processed
        for broker_host, broker_info in self.brokers.items():
            annotation = [
                {
                    "broker": self._process_helics_broker_metadata(self.config.helics),
                    "fed-count": broker_info["feds"],
                }
            ]
            self.app.add_annotation(broker_host, "helics/federate", annotation)

    def _generate_main_controller(
        self,
        config: Config,
        node: dict[str, Any],
        ips: dict[str, str],
        turbine_num: int,
        cfg_dir: str,
    ) -> None:
        tmpl = self.config.templates.get("default", {}).get("main-controller", {})
        anemo_tmpl = self.config.templates.get("default", {}).get("anemometer", {})
        md = tmpl.get("turbine", {})
        sbo = str(md.get("dnp3SBO", False)).lower()

        # Power Output Module
        turbine = ET.Element("wind-turbine")
        power = ET.SubElement(turbine, "power-output")
        ET.SubElement(power, "turbine-type").text = md.get("type", "E-126/4200")
        ET.SubElement(power, "hub-height").text = str(md.get("hubHeight", 135))
        ET.SubElement(power, "roughness-length").text = str(
            md.get("roughnessLength", 0.15)
        )

        # Weather Data Columns
        weather = tmpl.get("weather", {})
        data = ET.SubElement(power, "weather-data")
        for col in weather.get("columns", []):
            for tag in col["tags"]:
                ET.SubElement(
                    data, "column", {"name": col["name"], "height": str(tag["height"])}
                ).text = tag["name"]

        # Tags
        tags = ET.SubElement(power, "tags")
        ET.SubElement(tags, "cut-in").text = "turbine.cut-in"
        ET.SubElement(tags, "cut-out").text = "turbine.cut-out"
        ET.SubElement(tags, "output").text = "turbine.mw-output"
        ET.SubElement(tags, "emergency-stop").text = "turbine.emergency-stop"

        module = ET.Element("module", {"name": "turbine-power-output"})
        module.text = "ot-sim-wind-turbine-power-output-module {{config_file}}"
        config.append_to_root(turbine)
        config.append_to_cpu(module)

        # HELICS Module
        helics_conf = self.config.helics
        template_topic = md.get("helicsTopic")

        if helics_conf or template_topic:
            io = ET.Element("io", {"name": "helics-federate"})
            broker_ep = ET.SubElement(io, "broker-endpoint")
            federate_name = ET.SubElement(io, "federate-name")
            log_level = ET.SubElement(io, "federate-log-level")

            addr = self._process_helics_broker_metadata(helics_conf)
            assert addr, "Could not resolve HELICS broker address"

            broker_ep.text = addr
            federate_name.text = node["hostname"]
            log_level.text = helics_conf.get("log-level", "SUMMARY")

            # Default endpoint for publishing power output
            federate = helics_conf.get("federate", "OpenDSS")
            endpoint_name = helics_conf.get("endpoint", f"{federate}/updates")

            if endpoint_name:
                if "/" not in endpoint_name:
                    endpoint_name = f"{federate}/{endpoint_name}"

                endpoint = ET.Element("endpoint", {"name": endpoint_name})

                topic = (
                    helics_conf.get("topic")
                    or template_topic
                    or "wtg.{{turbine_id}}.mw"
                )

                replacements = {
                    "{{turbine_name}}": f"wtg-{turbine_num}",
                    "{{turbine_id}}": str(turbine_num),
                }
                for key, val in replacements.items():
                    topic = topic.replace(key, val)

                tag = ET.Element("tag")
                tag.attrib["key"] = topic
                tag.text = "turbine.mw-output"
                endpoint.append(tag)
                io.append(endpoint)

            config.append_to_root(io)
            module = ET.Element("module", {"name": "i/o"})
            module.text = "ot-sim-io-module {{config_file}}"
            config.append_to_cpu(module)

        # Node-RED Module
        nr_md = tmpl.get("node-red")
        if nr_md:
            nodered = NodeRed()
            nodered.init_xml_root(nr_md, "main-controller")
            nodered.to_xml()

            module = ET.Element("module", {"name": "node-red"})
            module.text = "ot-sim-node-red-module {{config_file}}"
            config.append_to_root(nodered.root)
            config.append_to_cpu(module)

            inject = nodered.needs_inject()
            if inject:
                shutil.copy(
                    inject["src"],
                    os.path.join(cfg_dir, os.path.basename(inject["dst"])),
                )

        # Logic Module
        logic_md = tmpl.get("logic", {})
        program = """
          manual_stop = false
          proto_stop = proto_emer_stop != 0
          stop = proto_stop || manual_stop
          feathered = stop || speed < cut_in || speed > cut_out
          target = direction > 180 ? direction - 180 : direction + 180
          error = target * dir_error
          adjust = abs(target - current_yaw) > error
          adjust = adjust && !feathered
          yaw_setpoint = adjust ? target : yaw_setpoint
          # hack to get yaw.dir-error tag published to DNP3 module
          dir_error = dir_error
          # hack to get turbine.emergency-stop tag published to DNP3 module
          proto_emer_stop = proto_emer_stop
        """
        variables = {
            "speed": {"value": 0, "tag": logic_md.get("speedTag", "speed.high")},
            "direction": {"value": 0, "tag": logic_md.get("directionTag", "dir.high")},
            "cut_in": {"value": 100, "tag": "turbine.cut-in"},
            "cut_out": {"value": 0, "tag": "turbine.cut-out"},
            "current_yaw": {"value": 0, "tag": "yaw.current"},
            "yaw_setpoint": {"value": 0, "tag": "yaw.setpoint"},
            "dir_error": {
                "value": logic_md.get("directionError", 0.04),
                "tag": "yaw.dir-error",
            },
            "proto_emer_stop": {"value": 0, "tag": "turbine.emergency-stop"},
            "feathered": {"value": 0},
        }
        logic = Logic()
        logic.init_xml_root("main-controller")
        logic.logic_to_xml(program, variables, period="1s", process_updates=True)
        module = ET.Element("module", {"name": "logic"})
        module.text = "ot-sim-logic-module {{config_file}}"
        config.append_to_root(logic.root)
        config.append_to_cpu(module)

        # Modbus Clients
        # Signal Converter (Anemometer)
        anemo_node = Box(
            {
                "hostname": f"wtg-{turbine_num}-signal-converter",
                "metadata": {"type": "signal-converter"},
                "topology": {"network": {"interfaces": [{"address": ips["anemo"]}]}},
            }
        )
        mb = Modbus()
        mb.init_xml_root("client", anemo_node, name="signal-converter")
        mb.registers_to_xml(self._get_anemometer_registers(anemo_tmpl))
        config.append_to_root(mb.root)

        # Yaw
        yaw_node = Box(
            {
                "hostname": f"wtg-{turbine_num}-yaw-controller",
                "metadata": {"type": "yaw-controller"},
                "topology": {"network": {"interfaces": [{"address": ips["yaw"]}]}},
            }
        )
        mb = Modbus()
        mb.init_xml_root("client", yaw_node, name="yaw-controller")
        mb.registers_to_xml(self._get_yaw_registers())
        config.append_to_root(mb.root)

        # Blades
        for i in range(1, 4):
            blade_node = Box(
                {
                    "hostname": f"wtg-{turbine_num}-blade-{i}",
                    "metadata": {},
                    "topology": {
                        "network": {"interfaces": [{"address": ips[f"blade{i}"]}]}
                    },
                }
            )
            mb = Modbus()
            mb.init_xml_root("client", blade_node, name=f"blade-{i}")
            mb.registers_to_xml(self._get_blade_registers())
            config.append_to_root(mb.root)

        module = ET.Element("module", {"name": "modbus"})
        module.text = "ot-sim-modbus-module {{config_file}}"
        config.append_to_cpu(module)

        # DNP3 Server
        dnp = DNP3()
        dnp.init_xml_root("server", Box(node))
        dnp.init_outstation_xml()
        registers = [
            Register("binary-read-write", "turbine.emergency-stop", {"sbo": sbo}),
            Register("analog-read-write", "yaw.dir-error", {"sbo": sbo}),
            Register("analog-read", "yaw.current"),
            Register("analog-read", "yaw.setpoint"),
            Register("analog-read", "turbine.mw-output"),
            Register("binary-read", "feathered"),
            *self._get_anemometer_registers(anemo_tmpl),
        ]
        dnp.registers_to_xml(registers)
        config.append_to_root(dnp.root)
        module = ET.Element("module", {"name": "dnp3"})
        module.text = "ot-sim-dnp3-module {{config_file}}"
        config.append_to_cpu(module)

    def _generate_anemometer(self, config: Config, node: dict[str, Any]) -> None:
        tmpl = self.config.templates.get("default", {}).get("anemometer", {})
        weather = tmpl.get("weather", {})

        # Only configure the anemometer if replayData is specified
        if weather.get("replayData"):
            dst_data = "/shared/weather.csv"

            turbine = ET.Element("wind-turbine")
            anemo = ET.SubElement(turbine, "anemometer")
            data = ET.SubElement(anemo, "weather-data")

            registers = []
            for col in weather.get("columns", []):
                ET.SubElement(data, "column", {"name": col["name"]}).text = col["tag"]
                registers.append(Register("analog-read", col["tag"], {"scaling": 2}))

            ET.SubElement(anemo, "data-path").text = dst_data

            module = ET.Element("module", {"name": "turbine-anemometer"})
            module.text = "ot-sim-wind-turbine-anemometer-module {{config_file}}"
            config.append_to_root(turbine)
            config.append_to_cpu(module)

            mb = Modbus()
            mb.init_xml_root("server", Box(node))
            mb.registers_to_xml(registers)
            module = ET.Element("module", {"name": "modbus"})
            module.text = "ot-sim-modbus-module {{config_file}}"
            config.append_to_root(mb.root)
            config.append_to_cpu(module)

    def _generate_yaw_controller(self, config: Config, node: dict[str, Any]) -> None:
        tmpl = self.config.templates.get("default", {}).get("yaw-controller", {})

        mb = Modbus()
        mb.init_xml_root("server", Box(node))
        mb.registers_to_xml(self._get_yaw_registers())
        module = ET.Element("module", {"name": "modbus"})
        module.text = "ot-sim-modbus-module {{config_file}}"
        config.append_to_root(mb.root)
        config.append_to_cpu(module)

        yaw_md = tmpl.get("yaw", {})
        program = f"""
          current_yaw = current_yaw == 0 ? yaw_setpoint : current_yaw
          adjust = yaw_setpoint != current_yaw
          dir = yaw_setpoint > current_yaw ? 1 : -1
          current_yaw = adjust ? current_yaw + (dir * {yaw_md.get("degreePerSecond", 0.1)}) : current_yaw
        """
        variables = {
            "current_yaw": {
                "value": yaw_md.get("initialPosition", 0),
                "tag": "yaw.current",
            },
            "yaw_setpoint": {"value": 0, "tag": "yaw.setpoint"},
        }
        logic = Logic()
        logic.init_xml_root("yaw-controller")
        logic.logic_to_xml(program, variables, period="1s", process_updates=True)
        module = ET.Element("module", {"name": "logic"})
        module.text = "ot-sim-logic-module {{config_file}}"
        config.append_to_root(logic.root)
        config.append_to_cpu(module)

    def _generate_blade_controller(self, config: Config, node: dict[str, Any]) -> None:
        mb = Modbus()
        mb.init_xml_root("server", Box(node))
        mb.registers_to_xml(self._get_blade_registers())
        module = ET.Element("module", {"name": "modbus"})
        module.text = "ot-sim-modbus-module {{config_file}}"
        config.append_to_root(mb.root)
        config.append_to_cpu(module)

    def _get_anemometer_registers(self, tmpl: dict[str, Any]) -> list[Register]:
        weather = tmpl.get("weather", {})
        registers = []
        for col in weather.get("columns", []):
            registers.append(Register("analog-read", col["tag"], {"scaling": 2}))
        return registers

    def _get_yaw_registers(self) -> list[Register]:
        return [
            Register("analog-read", "yaw.current", {"scaling": 2}),
            Register("analog-read-write", "yaw.setpoint", {"scaling": 2}),
        ]

    def _get_blade_registers(self) -> list[Register]:
        return [Register("binary-read-write", "feathered", {})]

    def get_additional_startup_commands(self, _index: int, _hostname: str) -> str:
        commands = [
            "sysctl -w net.ipv4.ip_forward=1",
            "tar -C / -xzf /wind-configs.tgz",
        ]
        return "\n".join(commands)

    def pre_post_start(self, app: AppBase, profile: dict[str, Any]) -> None:
        self.app = app
        self.config = WindTurbineConfig(**profile)

    def get_container_count(self, index: int) -> int:
        # Calculate containers for this node
        total_containers = self.config.count * 6
        per_node = self.config.containers_per_node

        # Full nodes
        if index * per_node <= total_containers:
            return per_node

        # Last node (remainder)
        remainder = total_containers % per_node
        if remainder > 0 and index == math.ceil(total_containers / per_node):
            return remainder

        return 0

    def get_template_name(self) -> str:
        return "wind_turbine.mako"

    def update_template_config(self, cfg: dict[str, Any]) -> None:
        cfg["NAMESPACE"] = "wind"

        # Source (VM): /scale/<hostname>/<i>/ -> Dest (Container): /etc/ot-sim/
        cfg["PER_CONTAINER_VOLUMES"] = [("/scale/{HOSTNAME}/{i}/", "/etc/ot-sim/")]
        cfg["SHARED_VOLUMES"] = []

        # Add shared volume for weather data if configured
        anemo_tmpl = self.config.templates.get("default", {}).get("anemometer", {})
        weather = anemo_tmpl.get("weather", {})
        if weather.get("replayData"):
            cfg["SHARED_VOLUMES"].append(("/scale/shared/", "/shared/"))

        # Parse node index from hostname to calculate global container index
        try:
            node_idx = int(cfg["HOSTNAME"].rsplit("-", 1)[-1])
        except ValueError:
            node_idx = 1

        container_details = self._get_container_details(node_idx)

        cfg["CONTAINER_HOSTNAMES"] = [d["hostname"] for d in container_details]
        cfg["CONTAINER_NETWORKS"] = [d["networks"] for d in container_details]
        cfg["CONTAINER_IPS"] = [d["ips"] for d in container_details]
        cfg["CONTAINER_GATEWAYS"] = [d["gateway"] for d in container_details]

    def get_plugin_config(self) -> Any:
        return self.config.to_dict()
