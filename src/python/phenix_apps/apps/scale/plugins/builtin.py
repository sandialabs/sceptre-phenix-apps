import math
from typing import Any, Dict

from phenix_apps.apps import AppBase
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.registry import register_plugin
from phenix_apps.common import logger


class BuiltinConfig:
    def __init__(self, **kwargs: Any):
        self.count = int(kwargs.get("count", 1))
        self.containers = int(kwargs.get("containers", 0))
        self.containers_per_node = int(kwargs.get("containers_per_node", 0))
        self.hostname_prefix = str(kwargs.get("hostname_prefix", "node"))

        if self.count < 1:
            raise ValueError("count must be >= 1")
        if self.containers < 0:
            raise ValueError("containers must be >= 0")
        if self.containers_per_node < 0:
            raise ValueError("containers_per_node must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


@register_plugin("builtin", "1.0.0")
class BuiltinV1(ScalePlugin):
    """
    The default builtin plugin (v1.0.0) for the Scale app.

    It provides generic infrastructure scaling capabilities, allowing users to:
    1. Deploy a specific number of VMs (using `count`).
    2. Calculate the number of VMs needed to host a specific volume of containers
       (using `containers` and `containers_per_node`).

    See `phenix_apps/apps/scale/plugins/builtin.md` for full documentation.
    """

    def pre_configure(self, _app: AppBase, profile: Dict[str, Any]) -> None:
        self.config = BuiltinConfig(**profile)

    def get_node_count(self) -> int:
        # If containers and containers_per_node are set, calculate nodes needed
        if self.config.containers > 0 and self.config.containers_per_node > 0:
            return math.ceil(self.config.containers / self.config.containers_per_node)
        return self.config.count

    def get_hostname(self, index: int) -> str:
        return f"{self.config.hostname_prefix}-{index}"

    def get_node_spec(self, index: int) -> Dict[str, Any]:
        return {
            "type": "VirtualMachine",
            "general": {
                "hostname": self.get_hostname(index),
                "vm_type": "kvm",
            },
            "hardware": {},
            "network": {"interfaces": []},
        }

    def on_node_configured(self, _app: AppBase, _index: int, _hostname: str) -> None:
        pass

    def get_additional_startup_commands(self, _index: int, _hostname: str) -> str:
        return ""

    def pre_post_start(self, _app: AppBase, profile: Dict[str, Any]) -> None:
        self.config = BuiltinConfig(**profile)

    def get_container_count(self, index: int) -> int:
        if self.config.containers > 0 and self.config.containers_per_node > 0:
            total = self.config.containers
            per_node = self.config.containers_per_node
            nodes = self.get_node_count()

            if index == nodes:
                return total - ((nodes - 1) * per_node)
            return per_node
        return 0

    def get_plugin_config(self) -> Any:
        return self.config.to_dict()


@register_plugin("builtin", "2.0.0")
class BuiltinV2(BuiltinV1):
    """
    A V2 example of the builtin plugin.
    It changes the hostname prefix to demonstrate versioning.
    """

    def pre_configure(self, _app: AppBase, profile: Dict[str, Any]) -> None:
        super().pre_configure(_app, profile)
        p_name = profile.get("name", "unknown")
        logger.log("INFO", f"Using builtin plugin v2.0.0 for profile '{p_name}'")

    def get_hostname(self, index: int) -> str:
        # Override hostname to show this is V2
        return f"v2-{self.config.hostname_prefix}-{index}"
