from typing import Any, Callable, Dict, Type


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, Dict[str, Type]] = {}

    def register_plugin(
        self, name: str, version: str = "1.0.0"
    ) -> Callable[[Type], Type]:
        def decorator(cls: Type) -> Type:
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
            # Simple string sort; for production consider semantic versioning parsing
            version = sorted(versions.keys())[-1]

        if version not in versions:
            raise ValueError(f"Plugin '{name}' version '{version}' not found.")

        cls = versions[version]
        return cls()


_registry = PluginRegistry()

register_plugin = _registry.register_plugin
get_plugin = _registry.get_plugin
PLUGIN_REGISTRY = _registry._plugins
