from collections.abc import Callable
from typing import Any


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, dict[str, type]] = {}

    def register_plugin(
        self, name: str, version: str = "1.0.0"
    ) -> Callable[[type], type]:
        def decorator(cls: type) -> type:
            if name not in self._plugins:
                self._plugins[name] = {}
            self._plugins[name][version] = cls
            return cls

        return decorator

    def get_plugin(self, name: str, version: str = "latest") -> Any:
        if name not in self._plugins:
            raise ValueError(f"Plugin '{name}' not found.")

        versions = self._plugins[name]
        if version == "latest":
            version = sorted(versions.keys())[-1]

        if version not in versions:
            raise ValueError(f"Plugin '{name}' version '{version}' not found.")

        cls = versions[version]
        return cls()


_registry = PluginRegistry()

register_plugin = _registry.register_plugin
get_plugin = _registry.get_plugin
PLUGIN_REGISTRY = _registry._plugins
