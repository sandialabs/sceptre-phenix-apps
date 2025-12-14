from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from phenix_apps.apps.scale.plugins.wind_turbine import WindTurbine, WindTurbineConfig


@pytest.fixture
def wind_turbine():
    plugin = WindTurbine()
    mock_app = MagicMock()
    return plugin, mock_app


def test_pre_configure_defaults(wind_turbine):
    """Test configuration with minimal profile."""
    plugin, mock_app = wind_turbine
    profile = {
        "name": "test-profile",
        "count": 5,
        "container_template": {"external_network": {"name": "EXT"}},
    }
    plugin.pre_configure(mock_app, profile)

    # Assert config object is created and has correct values
    assert isinstance(plugin.config, WindTurbineConfig)
    assert plugin.config.count == 5
    assert plugin.config.name == "test-profile"

    assert plugin.get_node_count() == 5
    spec = plugin.get_node_spec(1)
    assert spec["hardware"]["vcpus"] == 8
    assert spec["hardware"]["memory"] == 16384
    assert spec["general"]["hostname"] == "test-profile-1"


def test_pre_configure_overrides(wind_turbine):
    """Test configuration with node template overrides."""
    plugin, mock_app = wind_turbine
    profile = {
        "name": "custom-farm",
        "count": 2,
        "node_template": {
            "cpu": 4,
            "memory": 4096,
            "image": "custom.qc2",
            "network": {
                "interfaces": [{"name": "eth1", "vlan": "200"}]  # VM network override
            },
        },
        "container_template": {"external_network": {"name": "EXT"}},
    }
    plugin.pre_configure(mock_app, profile)

    # Assert config object is created and has correct values
    assert isinstance(plugin.config, WindTurbineConfig)
    assert plugin.config.count == 2
    assert plugin.config.node_template["cpu"] == 4

    assert plugin.get_node_count() == 2
    spec = plugin.get_node_spec(1)
    assert spec["hardware"]["vcpus"] == 4
    assert spec["hardware"]["memory"] == 4096
    assert spec["general"]["hostname"] == "custom-farm-1"


def test_config_validation(wind_turbine):
    """Test that invalid config raises ValueError."""
    plugin, mock_app = wind_turbine
    profile = {"name": "invalid-profile", "count": 0}
    with pytest.raises(ValidationError):
        plugin.pre_configure(mock_app, profile)

    # Test that external_network is required when count > 0
    profile_no_ext = {"name": "invalid-profile", "count": 1}
    with pytest.raises(ValueError, match="external_network must be defined"):
        plugin.pre_configure(mock_app, profile_no_ext)


def test_config_alias_parsing(wind_turbine):
    """Test that Pydantic aliases (ground-truth-module) are parsed correctly."""
    plugin, mock_app = wind_turbine
    profile = {
        "name": "alias-test",
        "count": 1,
        "container_template": {"external_network": {"name": "EXT"}},
        "ground-truth-module": {"elastic": {"endpoint": "http://es:9200"}},
    }

    plugin.pre_configure(mock_app, profile)

    assert plugin.config.ground_truth["elastic"]["endpoint"] == "http://es:9200"


def test_pre_post_start(wind_turbine):
    """Test that pre_post_start correctly initializes the config."""
    plugin, mock_app = wind_turbine
    profile = {
        "name": "post-start-profile",
        "count": 3,
        "container_template": {"external_network": {"name": "EXT"}},
    }
    # Ensure config is not set before
    assert not hasattr(plugin, "config")

    plugin.pre_post_start(mock_app, profile)

    # Assert config object is created and has correct values
    assert hasattr(plugin, "config")
    assert isinstance(plugin.config, WindTurbineConfig)
    assert plugin.config.count == 3
    assert plugin.get_node_count() == 3


def test_get_container_count(wind_turbine):
    """Ensure wind turbine plugin returns correct container count."""
    plugin, mock_app = wind_turbine
    profile = {
        "count": 1,
        "container_template": {"external_network": {"name": "EXT"}},
    }
    plugin.pre_configure(mock_app, profile)
    assert plugin.get_container_count(1) == 6


def test_ip_assignment_cidr_only(wind_turbine):
    """Test IP assignment when only network CIDR is provided."""
    plugin, mock_app = wind_turbine

    # Mock app methods needed for _get_container_details
    # _process_networks returns (net_str, net_info_list)
    mock_app._process_networks.return_value = ("test_net", [{"prefix": 24}])
    mock_app._get_gateway.return_value = None

    # Case 1: Network address provided (e.g. .0/24) -> Should start at .1
    profile = {
        "name": "cidr-test",
        "count": 1,
        "container_template": {
            "external_network": {"name": "EXT", "network": "192.168.50.0/24"}
        },
    }

    plugin.pre_configure(mock_app, profile)
    details = plugin._get_container_details(1)
    main_ctrl = next(d for d in details if d["type"] == "main-controller")

    # Expected IP: 192.168.50.1
    assert main_ctrl["topology_ip"] == "192.168.50.1"
    assert main_ctrl["ips"][0] == "192.168.50.1/24"

    # Case 2: Specific IP provided in CIDR (e.g. .10/24) -> Should start at .10
    profile2 = {
        "name": "cidr-test-2",
        "count": 1,
        "container_template": {
            "external_network": {"name": "EXT", "network": "192.168.50.10/24"}
        },
    }
    plugin.pre_configure(mock_app, profile2)
    details2 = plugin._get_container_details(1)
    main_ctrl2 = next(d for d in details2 if d["type"] == "main-controller")

    assert main_ctrl2["topology_ip"] == "192.168.50.10"
    assert main_ctrl2["ips"][0] == "192.168.50.10/24"


def test_on_node_configured(wind_turbine, mocker):
    """Test on_node_configured logic (file generation, injection)."""
    plugin, mock_app = wind_turbine
    mock_app.app_dir = "/tmp/app_dir"
    mock_app.exp_dir = "/tmp/exp_dir"
    # Mock _process_networks return
    mock_app._process_networks.return_value = ("net_str", [])
    # Mock extract_node for HELICS broker resolution
    mock_node = MagicMock()
    mock_node.network.interfaces = [{"name": "eth0", "address": "10.0.0.1"}]
    mock_app.extract_node.return_value = mock_node

    profile = {
        "name": "test-wtg",
        "count": 1,
        "container_template": {"external_network": {"name": "EXT"}},
        "helics": {"broker": {"hostname": "broker|eth0"}},
    }
    plugin.pre_configure(mock_app, profile)

    # Mock dependencies
    mock_makedirs = mocker.patch("phenix_apps.apps.scale.plugins.wind_turbine.os.makedirs")
    mock_tarfile = mocker.patch("phenix_apps.apps.scale.plugins.wind_turbine.tarfile.open")
    mocker.patch("phenix_apps.apps.scale.plugins.wind_turbine.shutil.copy")

    # Mock Config to avoid XML errors and file writing
    mock_config_cls = mocker.patch("phenix_apps.apps.scale.plugins.wind_turbine.Config")
    mock_config_instance = mock_config_cls.return_value

    # Run
    plugin.on_node_configured(mock_app, 1, "test-wtg-1")

    # Assertions
    # 1. Check directories created (1 for each of 6 containers)
    assert mock_makedirs.call_count >= 6

    # 2. Check config files generated (6 configs)
    assert mock_config_instance.to_file.call_count == 6

    # 3. Check tarball creation
    mock_tarfile.assert_called_with("/tmp/exp_dir/wind-configs.tgz", "w:gz")

    # 4. Check injection
    mock_app.add_inject.assert_any_call(
        hostname="test-wtg-1",
        inject={"src": "/tmp/exp_dir/wind-configs.tgz", "dst": "/wind-configs.tgz"},
    )
