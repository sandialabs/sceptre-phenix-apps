import math
from typing import Any

from pydantic import BaseModel, Field

from phenix_apps.apps import AppBase
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.registry import register_plugin
from phenix_apps.common.logger import logger


class BuiltinConfig(BaseModel):
    count: int = Field(default=1, ge=1)
    containers: int = Field(default=0, ge=0)
    containers_per_node: int = Field(default=0, ge=0)
    hostname_prefix: str = "node"
    # Ignore extra fields (like node_template, container_template) that are
    # handled by the core Scale app, not this plugin.
    model_config = {"extra": "ignore", "validate_assignment": True}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


@register_plugin("builtin", "1.0.0")
class BuiltinV1(ScalePlugin):
    """
    The default builtin plugin (v1.0.0) for the Scale app.

    It provides generic infrastructure scaling capabilities, supporting two modes:
    1. **VM Scaling**: Deploy a specific number of VMs (using `count`).
    2. **Nested Containers**: Calculate the number of VMs needed to host a specific volume of containers
       (using `containers` and `containers_per_node`).

    See `phenix_apps/apps/scale/plugins/builtin.md` for full documentation.
    """

    def pre_configure(self, _app: AppBase, profile: dict[str, Any]) -> None:
        self.config = BuiltinConfig(**profile)

    def get_node_count(self) -> int:
        # If containers and containers_per_node are set, calculate nodes needed
        if self.config.containers > 0 and self.config.containers_per_node > 0:
            return math.ceil(self.config.containers / self.config.containers_per_node)
        return self.config.count

    def get_hostname(self, index: int) -> str:
        return f"{self.config.hostname_prefix}-{index}"

    def get_node_spec(self, index: int) -> dict[str, Any]:
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

    def pre_post_start(self, _app: AppBase, profile: dict[str, Any]) -> None:
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

    def pre_configure(self, _app: AppBase, profile: dict[str, Any]) -> None:
        super().pre_configure(_app, profile)
        p_name = profile.get("name", "unknown")
        logger.info(f"Using builtin plugin v2.0.0 for profile '{p_name}'")

    def get_hostname(self, index: int) -> str:
        # Override hostname to show this is V2
        return f"v2-{self.config.hostname_prefix}-{index}"
