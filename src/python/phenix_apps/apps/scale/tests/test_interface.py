import pytest
from phenix_apps.apps.scale.interface import ScalePlugin


class ConcretePlugin(ScalePlugin):
    """Minimal concrete implementation for testing abstract base class methods."""

    def pre_configure(self, app, profile):
        pass

    def get_node_count(self):
        return 0

    def get_node_spec(self, index):
        return {}

    def get_hostname(self, index):
        return ""

    def on_node_configured(self, app, index, hostname):
        pass

    def get_additional_startup_commands(self, index, hostname):
        return ""

    def pre_post_start(self, app, profile):
        pass

    def get_container_count(self, index):
        return 0


def test_validate_profile_valid(mocker):
    """Test validate_profile with valid inputs."""
    mocker.patch(
        "phenix_apps.apps.scale.registry.PLUGIN_REGISTRY", {"valid-plugin": {}}
    )
    plugin = ConcretePlugin()

    # String plugin name
    plugin.validate_profile(None, {"name": "p1", "plugin": "valid-plugin"})

    # Dict plugin spec
    plugin.validate_profile(None, {"name": "p2", "plugin": {"name": "valid-plugin"}})


def test_validate_profile_errors(mocker):
    """Test validate_profile error conditions."""
    mocker.patch("phenix_apps.apps.scale.registry.PLUGIN_REGISTRY", {})
    plugin = ConcretePlugin()

    # Missing name
    with pytest.raises(ValueError, match="Profile missing required field 'name'"):
        plugin.validate_profile(None, {"plugin": "foo"})

    # Missing plugin
    with pytest.raises(ValueError, match="Profile missing required field 'plugin'"):
        plugin.validate_profile(None, {"name": "foo"})

    # Unregistered plugin
    with pytest.raises(
        ValueError, match="Plugin 'ghost' in profile 'foo' is not registered"
    ):
        plugin.validate_profile(None, {"name": "foo", "plugin": "ghost"})


def test_default_methods():
    """Test default implementations of optional methods."""
    plugin = ConcretePlugin()

    # get_template_name default
    assert plugin.get_template_name() == "minimega.mako"

    # update_template_config default (noop)
    cfg = {"a": 1}
    plugin.update_template_config(cfg)
    assert cfg == {"a": 1}

    # get_plugin_config default
    assert plugin.get_plugin_config() is None
    plugin.profile = {"test": "data"}
    assert plugin.get_plugin_config() == {"test": "data"}