"""
Unit tests for the Scale logic and plugin compliance.
"""

import importlib
import pkgutil
from unittest.mock import MagicMock

import pytest
from box import Box
from pydantic import ValidationError

import phenix_apps.apps.scale.plugins
from phenix_apps.apps.scale.app import Scale
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.plugins.builtin import BuiltinConfig, BuiltinV1, BuiltinV2
from phenix_apps.apps.scale.registry import PLUGIN_REGISTRY
from phenix_apps.common import settings


@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    """Dynamically discover and load all plugins once for all tests."""
    # Configure logger to write to stdout/stderr instead of file
    settings.PHENIX_LOG_FILE = None

    if hasattr(phenix_apps.apps.scale.plugins, "__path__"):
        for _, name, _ in pkgutil.iter_modules(phenix_apps.apps.scale.plugins.__path__):
            try:
                importlib.import_module(f"phenix_apps.apps.scale.plugins.{name}")
            except Exception:
                # Fail gracefully if a plugin can't be imported,
                # the compliance test will catch it.
                pass


def test_plugins_compliance():
    """Verify that all registered plugins strictly implement the ScalePlugin interface."""
    plugins_to_test = []
    for key, value in PLUGIN_REGISTRY.items():
        if isinstance(value, dict):
            for ver, cls in value.items():
                plugins_to_test.append((f"{key} (v{ver})", cls))
        else:
            # Handle non-versioned registration for simplicity in testing
            plugins_to_test.append((key, value))

    assert len(plugins_to_test) > 0, "No plugins were discovered and registered."

    for name, plugin_cls in plugins_to_test:
        assert issubclass(plugin_cls, ScalePlugin), (
            f"Plugin '{name}' does not inherit from ScalePlugin"
        )
        missing = getattr(plugin_cls, "__abstractmethods__", set())
        assert not missing, (
            f"Plugin '{name}' fails to implement abstract methods: {missing}"
        )


def test_plugin_loading_builtin(mocker):
    """Test that the builtin plugin is loaded by default."""
    mocker.patch("phenix_apps.apps.scale.app.os.makedirs")
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)
    mock_get_plugin = mocker.patch("phenix_apps.apps.scale.app.get_plugin")

    scale_app = Scale()
    scale_app.metadata = {}
    scale_app.exp_dir = "/tmp"
    scale_app.name = "scale"

    mock_plugin_instance = MagicMock()
    mock_get_plugin.return_value = mock_plugin_instance

    profile = {"plugin": "builtin"}
    plugin = scale_app._get_plugin_instance(profile)

    mock_get_plugin.assert_called_with("builtin", "latest")
    assert plugin == mock_plugin_instance


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


def test_builtin_container_calculation():
    """Test node count calculation based on container settings."""
    # Case 1: Just count
    data = {"count": 5}
    plugin = BuiltinV1()
    plugin.pre_configure(None, data)
    assert plugin.get_node_count() == 5
    assert plugin.get_container_count(1) == 0

    # Case 2: Containers and containers_per_node (exact fit)
    # 100 containers, 10 per node -> 10 nodes
    data = {"containers": 100, "containers_per_node": 10}
    plugin.pre_configure(None, data)
    assert plugin.get_node_count() == 10
    assert plugin.get_container_count(1) == 10
    assert plugin.get_container_count(10) == 10

    # Case 3: Containers and containers_per_node (remainder)
    # 105 containers, 10 per node -> 11 nodes (10 full, 1 partial)
    data = {"containers": 105, "containers_per_node": 10}
    plugin.pre_configure(None, data)
    assert plugin.get_node_count() == 11
    assert plugin.get_container_count(1) == 10
    assert plugin.get_container_count(11) == 5


def test_post_start_logic(mocker):
    """Test post_start logic with mocked minimega and file operations."""
    mocker.patch("phenix_apps.apps.scale.app.logger")
    mocker.patch("phenix_apps.apps.scale.app.Progress")
    mock_minimega = mocker.patch("phenix_apps.apps.scale.app.minimega")
    mocker.patch("phenix_apps.apps.scale.app.utils")
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)

    mock_mm_conn = MagicMock()
    mock_minimega.connect.return_value = mock_mm_conn

    app = Scale()
    app.name = "scale"
    app.exp_name = "test_exp"
    app.files_dir = "/tmp/files"
    app.templates_dir = "/tmp/templates"
    app.metadata = {"name": "default", "plugin": "builtin", "count": 2}
    app.dryrun = False
    app._get_profiles = MagicMock(return_value=[app.metadata])
    app._print_summary_table = MagicMock()

    mock_plugin = MagicMock()
    mock_plugin.get_node_count.return_value = 2
    mock_plugin.get_hostname.side_effect = lambda i: f"node-{i}"
    mock_plugin.get_container_count.return_value = 1
    app._get_plugin_instance = MagicMock(return_value=mock_plugin)

    app._process_networks = MagicMock(return_value=None)
    app._get_gateway = MagicMock(return_value=None)

    # Mock open to prevent real file writing
    mocker.patch("builtins.open", mocker.mock_open())

    app.post_start()

    mock_minimega.connect.assert_called_with(namespace="test_exp")
    assert mock_mm_conn.cc_filter.call_count == 2
    assert mock_mm_conn.cc_send.call_count == 2
    mock_mm_conn.cc_filter.assert_any_call(filter="name=node-1")
    mock_mm_conn.cc_send.assert_any_call("/tmp/files/node-1.mm")


def test_discover_plugins(mocker):
    """Test that _discover_plugins method correctly imports modules based on metadata."""
    mocker.patch("phenix_apps.apps.scale.app.logger")
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)

    app = Scale()
    # Mock get_profiles to return profiles with specific plugins
    app.get_profiles = MagicMock(
        return_value=[{"plugin": "builtin"}, {"plugin": {"name": "wind"}}]
    )

    # Patch PLUGIN_REGISTRY to be empty so imports are attempted
    mocker.patch("phenix_apps.apps.scale.app.PLUGIN_REGISTRY", {})
    mocker.patch("phenix_apps.apps.scale.app.entry_points", return_value=[])
    mock_import = mocker.patch("phenix_apps.apps.scale.app.importlib.import_module")

    app._discover_plugins()

    mock_import.assert_any_call("phenix_apps.apps.scale.plugins.builtin")
    mock_import.assert_any_call("phenix_apps.apps.scale.plugins.wind")


def test_configure_adds_nodes_to_topology(mocker):
    """Test that configure method adds nodes to the experiment topology."""
    mocker.patch("phenix_apps.apps.scale.app.os.makedirs")
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)

    app = Scale()
    # Manually set up attributes expected by AppBase/Scale
    app.name = "scale"
    app.experiment = Box(
        {"spec": {"topology": {"nodes": []}, "scenario": {"apps": []}}}
    )
    app.metadata = {"profiles": [{"name": "test", "plugin": "builtin", "count": 2}]}
    app.app_dir = "/tmp/scale"
    app.exp_name = "test_exp"

    # Mock methods used in configure
    app.get_profiles = MagicMock(return_value=app.metadata["profiles"])
    app._apply_node_defaults = MagicMock()
    app._configure_node_common = MagicMock()
    app._print_summary_table = MagicMock()

    # Mock plugin
    mock_plugin = MagicMock()
    mock_plugin.get_node_count.return_value = 2
    mock_plugin.get_node_spec.side_effect = [
        {"general": {"hostname": "node-1"}, "type": "VirtualMachine"},
        {"general": {"hostname": "node-2"}, "type": "VirtualMachine"},
    ]
    # Mock other plugin methods
    mock_plugin.validate_profile.return_value = None
    mock_plugin.pre_configure.return_value = None
    mock_plugin.get_plugin_config.return_value = {}
    mock_plugin.on_node_configured.return_value = None
    mock_plugin.get_container_count.return_value = 0
    mock_plugin.get_additional_startup_commands.return_value = ""

    app._get_plugin_instance = MagicMock(return_value=mock_plugin)

    # Run configure
    app.configure()

    # Verify nodes were added to topology
    assert len(app.experiment.spec.topology.nodes) == 2
    assert app.experiment.spec.topology.nodes[0].general.hostname == "node-1"
    assert app.experiment.spec.topology.nodes[1].general.hostname == "node-2"


def test_startup_script_generation(mocker):
    """Test that startup script is generated with correct content."""
    mocker.patch("phenix_apps.apps.scale.app.os.makedirs")
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)

    app = Scale()
    app.name = "scale"
    app.exp_name = "test_exp"
    app.app_dir = "/tmp/scale"
    app.add_inject = MagicMock()

    mock_plugin = MagicMock()

    # Case 1: With additional commands
    mock_plugin.get_additional_startup_commands.return_value = "echo 'custom command'"

    mock_file = mocker.patch("builtins.open", mocker.mock_open())
    app._configure_node_common(mock_plugin, 1, "node-1", {})

    mock_file.assert_called_with("/tmp/scale/node-1-startup.sh", "w")
    handle = mock_file()

    expected_content = """echo 'STARTING...'
echo 'custom command'
while [ ! -S /tmp/minimega/minimega ]; do sleep 1; done
while [ ! -f /tmp/miniccc/files/test_exp/node-1.mm ]; do sleep 1; done
ovs-vsctl add-br test_exp
ovs-vsctl add-port test_exp ens1
mm read /tmp/miniccc/files/test_exp/node-1.mm
echo 'DONE!'
"""
    handle.write.assert_called_with(expected_content)

    # Case 2: Without additional commands (None or empty string)
    mock_plugin.get_additional_startup_commands.return_value = None

    mock_file = mocker.patch("builtins.open", mocker.mock_open())
    app._configure_node_common(mock_plugin, 1, "node-2", {})

    handle = mock_file()
    expected_content_empty = """echo 'STARTING...'

while [ ! -S /tmp/minimega/minimega ]; do sleep 1; done
while [ ! -f /tmp/miniccc/files/test_exp/node-2.mm ]; do sleep 1; done
ovs-vsctl add-br test_exp
ovs-vsctl add-port test_exp ens1
mm read /tmp/miniccc/files/test_exp/node-2.mm
echo 'DONE!'
"""
    handle.write.assert_called_with(expected_content_empty)

    # Case 3: With multiline additional commands
    mock_plugin.get_additional_startup_commands.return_value = "cmd1\ncmd2"

    mock_file = mocker.patch("builtins.open", mocker.mock_open())
    app._configure_node_common(mock_plugin, 1, "node-3", {})

    handle = mock_file()
    expected_content_multiline = """echo 'STARTING...'
cmd1
cmd2
while [ ! -S /tmp/minimega/minimega ]; do sleep 1; done
while [ ! -f /tmp/miniccc/files/test_exp/node-3.mm ]; do sleep 1; done
ovs-vsctl add-br test_exp
ovs-vsctl add-port test_exp ens1
mm read /tmp/miniccc/files/test_exp/node-3.mm
echo 'DONE!'
"""
    handle.write.assert_called_with(expected_content_multiline)


def test_builtin_v1_methods():
    """Test BuiltinV1 specific methods."""
    plugin = BuiltinV1()
    profile = {"count": 1, "hostname_prefix": "test"}
    plugin.pre_configure(None, profile)

    # get_hostname
    assert plugin.get_hostname(1) == "test-1"

    # get_node_spec
    spec = plugin.get_node_spec(1)
    assert spec["general"]["hostname"] == "test-1"
    assert spec["type"] == "VirtualMachine"
    assert spec["general"]["vm_type"] == "kvm"

    # on_node_configured (noop)
    plugin.on_node_configured(None, 1, "test-1")

    # get_additional_startup_commands (empty)
    assert plugin.get_additional_startup_commands(1, "test-1") == ""


def test_builtin_v2_methods(mocker):
    """Test BuiltinV2 specific methods."""
    # Mock logger to verify call
    mock_logger = mocker.patch("phenix_apps.apps.scale.plugins.builtin.logger")

    plugin = BuiltinV2()
    profile = {"count": 1, "hostname_prefix": "test", "name": "my-profile"}

    plugin.pre_configure(None, profile)

    # Verify logging
    mock_logger.info.assert_called_with("Using builtin plugin v2.0.0 for profile 'my-profile'")

    # Verify hostname override
    assert plugin.get_hostname(1) == "v2-test-1"


def test_apply_node_defaults(mocker):
    """Test _apply_node_defaults logic."""
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)
    app = Scale()

    # Case 1: Global defaults
    spec = {}
    profile = {}
    app._apply_node_defaults(spec, profile)

    assert spec["type"] == "VirtualMachine"
    assert spec["general"]["vm_type"] == "kvm"
    assert spec["hardware"]["vcpus"] == 1
    assert spec["hardware"]["memory"] == 512
    assert spec["hardware"]["drives"][0]["image"] == "minimeta.qc2"
    assert spec["network"]["interfaces"][0]["name"] == "ens1"

    # Case 2: Profile overrides
    spec = {}
    profile = {
        "node_template": {
            "cpu": 4,
            "memory": 2048,
            "image": "custom.img",
            "network": {"interfaces": [{"name": "eth0"}]},
        }
    }
    app._apply_node_defaults(spec, profile)

    assert spec["hardware"]["vcpus"] == 4
    assert spec["hardware"]["memory"] == 2048
    assert spec["hardware"]["drives"][0]["image"] == "custom.img"
    assert spec["network"]["interfaces"][0]["name"] == "eth0"


def test_process_networks(mocker):
    """Test _process_networks logic."""
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)
    mock_logger = mocker.patch("phenix_apps.apps.scale.app.logger")

    app = Scale()
    app.exp_name = "test_exp"
    app.dryrun = False
    app.experiment = Box({"status": {"vlans": {"MGMT": 100}}})

    # Case 1: Valid VLAN
    networks = [{"name": "MGMT", "network": "192.168.1.10/24"}]
    net_str, nets = app._process_networks(networks)

    assert "test_exp,100" in net_str
    assert str(nets[0]["addr"]) == "192.168.1.10"
    assert nets[0]["prefix"] == 24

    # Case 2: Missing VLAN (dryrun=False)
    networks = [{"name": "MISSING", "network": "10.0.0.1/24"}]
    net_str, nets = app._process_networks(networks)

    # Should log warning and skip
    mock_logger.warning.assert_called_with("VLAN not found: MISSING")
    assert net_str == ""
    assert len(nets) == 0

    # Case 3: Dryrun
    app.dryrun = True
    networks = [{"name": "MISSING", "network": "10.0.0.1/24"}]
    net_str, nets = app._process_networks(networks)

    assert "test_exp,100" in net_str
    assert str(nets[0]["addr"]) == "10.0.0.1"


def test_get_gateway(mocker):
    """Test _get_gateway logic."""
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)
    mock_logger = mocker.patch("phenix_apps.apps.scale.app.logger")

    app = Scale()
    app.dryrun = False
    app.experiment = Box({"status": {"vlans": {"MGMT": 100}}})

    # Case 1: IP address
    assert app._get_gateway("1.2.3.4") == "1.2.3.4"

    # Case 2: VLAN name (tap found)
    mock_tap_app = Box({"metadata": {"taps": [{"vlan": "MGMT", "ip": "1.2.3.1/24"}]}})
    app.extract_app = MagicMock(return_value=mock_tap_app)

    assert app._get_gateway("MGMT") == "1.2.3.1"

    # Case 3: VLAN name (tap not found)
    app.extract_app = MagicMock(return_value=None)
    assert app._get_gateway("MGMT") is None
    mock_logger.error.assert_called_with("Tap app not found! Required for gateway resolution.")
