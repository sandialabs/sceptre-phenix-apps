"""
Unit tests for the Scale builtin plugin.
"""

import pytest
from pydantic import ValidationError

from phenix_apps.apps.scale.plugins.builtin import BuiltinConfig, BuiltinV1, BuiltinV2


def test_builtin_config_validation():
    """Test validation for builtin config."""
    # Valid config
    data = {"count": 5}
    config = BuiltinConfig(**data)
    assert config.count == 5

    # Invalid config (count < 1)
    data = {"count": 0}
    with pytest.raises(ValidationError):
        BuiltinConfig(**data)

    # Test assignment validation
    config = BuiltinConfig(count=5)
    with pytest.raises(ValidationError):
        config.count = 0


def test_builtin_container_calculation(mock_scale_app):
    """Test node count calculation based on container settings."""
    # Case 1: Just count
    data = {"count": 5}
    plugin = BuiltinV1()
    plugin.pre_configure(mock_scale_app, data)
    assert plugin.get_node_count() == 5
    assert plugin.get_container_count(1) == 0

    # Case 2: Containers and containers_per_node (exact fit)
    # 100 containers, 10 per node -> 10 nodes
    data = {"containers": 100, "containers_per_node": 10}
    plugin.pre_configure(mock_scale_app, data)
    assert plugin.get_node_count() == 10
    assert plugin.get_container_count(1) == 10
    assert plugin.get_container_count(10) == 10

    # Case 3: Containers and containers_per_node (remainder)
    # 105 containers, 10 per node -> 11 nodes (10 full, 1 partial)
    data = {"containers": 105, "containers_per_node": 10}
    plugin.pre_configure(mock_scale_app, data)
    assert plugin.get_node_count() == 11
    assert plugin.get_container_count(1) == 10
    assert plugin.get_container_count(11) == 5


def test_builtin_v1_methods(mock_scale_app):
    """Test BuiltinV1 specific methods."""
    plugin = BuiltinV1()
    profile = {"count": 1, "hostname_prefix": "test"}
    plugin.pre_configure(mock_scale_app, profile)

    # get_hostname
    assert plugin.get_hostname(1) == "test-1"

    # get_node_spec
    spec = plugin.get_node_spec(1)
    assert spec["general"]["hostname"] == "test-1"
    assert spec["type"] == "VirtualMachine"
    assert spec["general"]["vm_type"] == "kvm"

    # on_node_configured (noop)
    plugin.on_node_configured(mock_scale_app, 1, "test-1")

    # get_additional_startup_commands (empty)
    assert plugin.get_additional_startup_commands(1, "test-1") == ""


def test_builtin_v2_methods(mocker, mock_scale_app):
    """Test BuiltinV2 specific methods."""
    # Mock logger to verify call
    mock_logger = mocker.patch("phenix_apps.apps.scale.plugins.builtin.plugin.logger")

    plugin = BuiltinV2()
    profile = {"count": 1, "hostname_prefix": "test", "name": "my-profile"}

    plugin.pre_configure(mock_scale_app, profile)

    # Verify logging
    mock_logger.info.assert_called_with(
        "Using builtin plugin v2.0.0 for profile 'my-profile'"
    )

    # Verify hostname override
    assert plugin.get_hostname(1) == "v2-test-1"
