import pytest
from phenix_apps.apps.scale.registry import PluginRegistry


class MockPlugin:
    pass


def test_registry_lifecycle():
    registry = PluginRegistry()

    # 1. Register a plugin
    @registry.register_plugin("my-plugin", "1.0.0")
    class MyPluginV1(MockPlugin):
        pass

    # Verify internal state
    assert "my-plugin" in registry._plugins
    assert "1.0.0" in registry._plugins["my-plugin"]
    assert registry._plugins["my-plugin"]["1.0.0"] == MyPluginV1

    # 2. Register a newer version
    @registry.register_plugin("my-plugin", "2.0.0")
    class MyPluginV2(MockPlugin):
        pass

    # 3. Get specific version
    instance = registry.get_plugin("my-plugin", "1.0.0")
    assert isinstance(instance, MyPluginV1)

    # 4. Get latest version
    instance = registry.get_plugin("my-plugin")
    assert isinstance(instance, MyPluginV2)

    instance = registry.get_plugin("my-plugin", "latest")
    assert isinstance(instance, MyPluginV2)


def test_registry_errors():
    registry = PluginRegistry()

    # Plugin not found
    with pytest.raises(ValueError, match="Plugin 'ghost' not found"):
        registry.get_plugin("ghost")

    # Register a plugin
    @registry.register_plugin("exists", "1.0.0")
    class Exists(MockPlugin):
        pass

    # Version not found
    with pytest.raises(ValueError, match="Plugin 'exists' version '2.0.0' not found"):
        registry.get_plugin("exists", "2.0.0")