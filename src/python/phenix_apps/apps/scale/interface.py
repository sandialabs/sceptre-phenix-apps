from abc import ABC, abstractmethod
from typing import Any

from phenix_apps.apps import AppBase


class ScalePlugin(ABC):
    """
    Abstract Base Class for Scale App plugins.
    Enforces implementation of required lifecycle methods.
    """

    def validate_profile(self, app: AppBase, profile: dict[str, Any]) -> None:
        """Ensure required profile fields are present."""
        if "name" not in profile:
            raise ValueError("Profile missing required field 'name'")

        # Import here to avoid circular dependency
        from phenix_apps.apps.scale.registry import PLUGIN_REGISTRY

        plugin_spec = profile.get("plugin")
        if not plugin_spec:
            raise ValueError("Profile missing required field 'plugin'")

        plugin_name = (
            plugin_spec.get("name") if isinstance(plugin_spec, dict) else plugin_spec
        )
        if plugin_name not in PLUGIN_REGISTRY:
            raise ValueError(
                f"Plugin '{plugin_name}' in profile '{profile.get('name')}' is not registered."
            )

    @abstractmethod
    def pre_configure(self, app: AppBase, profile: dict[str, Any]) -> None:
        """Perform initial configuration setup."""
        ...

    @abstractmethod
    def get_node_count(self) -> int:
        """Return the number of nodes to deploy."""
        ...

    @abstractmethod
    def get_node_spec(self, index: int) -> dict[str, Any]:
        """Return the topology node specification for the given index (1-based)."""
        ...

    @abstractmethod
    def get_hostname(self, index: int) -> str:
        """Return the hostname for the given index (1-based)."""
        ...

    @abstractmethod
    def on_node_configured(self, app: AppBase, index: int, hostname: str) -> None:
        """Perform custom actions after a node is added to topology."""
        ...

    @abstractmethod
    def get_additional_startup_commands(self, index: int, hostname: str) -> str:
        """Return additional bash commands to prepend to the startup script."""
        ...

    @abstractmethod
    def pre_post_start(self, app: AppBase, profile: dict[str, Any]) -> None:
        """Perform initial post-start setup."""
        ...

    @abstractmethod
    def get_container_count(self, index: int) -> int:
        """Return the number of containers for the given node index."""
        ...

    def get_template_name(self) -> str:
        """Return the name of the minimega template to use."""
        return "minimega.mako"

    def update_template_config(self, cfg: dict[str, Any]) -> None:
        """Update the template configuration dictionary."""
        pass

    def get_plugin_config(self) -> Any:
        """Return the internal configuration of the plugin for debugging."""
        return getattr(self, "profile", None)
