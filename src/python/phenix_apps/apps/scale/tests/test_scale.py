"""
Unit tests for the Scale logic and plugin compliance.
"""

import logging
from unittest.mock import MagicMock

import pytest
from box import Box

from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.registry import PLUGIN_REGISTRY


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


def test_plugin_loading_builtin(mocker, mock_scale_app):
    """Test that the builtin plugin is loaded by default."""
    mock_get_plugin = mocker.patch("phenix_apps.apps.scale.app.get_plugin")

    scale_app = mock_scale_app

    mock_plugin_instance = MagicMock()
    mock_get_plugin.return_value = mock_plugin_instance

    profile = {"plugin": "builtin"}
    plugin = scale_app._get_plugin_instance(profile)

    mock_get_plugin.assert_called_with("builtin", "latest")
    assert plugin == mock_plugin_instance


def test_post_start_logic(mocker, mock_scale_app, mock_minimega):
    """Test post_start logic with mocked minimega and file operations."""
    mocker.patch("phenix_apps.apps.scale.app.logger")
    mocker.patch("phenix_apps.apps.scale.app.Progress")
    mocker.patch("phenix_apps.apps.scale.app.utils")

    mock_mm_conn = mock_minimega

    app = mock_scale_app
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

    assert mock_mm_conn.cc_filter.call_count == 2
    assert mock_mm_conn.cc_send.call_count == 2
    mock_mm_conn.cc_filter.assert_any_call(filter="name=node-1")
    mock_mm_conn.cc_send.assert_any_call(f"{app.files_dir}/node-1.mm")


def test_discover_plugins(mocker, mock_scale_app):
    """Test that _discover_plugins method correctly loads entry points."""
    mocker.patch("phenix_apps.apps.scale.app.logger")

    app = mock_scale_app

    # Mock entry point
    mock_ep = MagicMock()
    mock_ep.name = "test_plugin"
    mock_ep.load = MagicMock()

    # Patch entry_points to return our mock
    mocker.patch("phenix_apps.apps.scale.app.entry_points", return_value=[mock_ep])

    app._discover_plugins()

    mock_ep.load.assert_called_once()


def test_configure_adds_nodes_to_topology(mocker, mock_scale_app):
    """Test that configure method adds nodes to the experiment topology."""
    app = mock_scale_app

    # Reset experiment for this test
    app.experiment = Box(
        {"spec": {"topology": {"nodes": []}, "scenario": {"apps": []}}}
    )
    app.metadata = {"profiles": [{"name": "test", "plugin": "builtin", "count": 2}]}

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


def test_startup_script_generation(mocker, mock_scale_app):
    """Test that startup script is generated with correct content."""
    app = mock_scale_app
    app.add_inject = MagicMock()

    mock_plugin = MagicMock()

    # Case 1: With additional commands
    mock_plugin.get_additional_startup_commands.return_value = "echo 'custom command'"

    mock_file = mocker.patch("builtins.open", mocker.mock_open())
    app._configure_node_common(mock_plugin, 1, "node-1", {})

    mock_file.assert_called_with(f"{app.app_dir}/node-1-startup.sh", "w")
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


def test_apply_node_defaults(mocker, mock_scale_app):
    """Test _apply_node_defaults logic."""
    app = mock_scale_app

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


def test_process_networks(mocker, mock_scale_app):
    """Test _process_networks logic."""
    mock_logger = mocker.patch("phenix_apps.apps.scale.app.logger")

    app = mock_scale_app
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


def test_get_gateway(mocker, mock_scale_app):
    """Test _get_gateway logic."""
    mock_logger = mocker.patch("phenix_apps.apps.scale.app.logger")

    app = mock_scale_app
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


def test_duplicate_plugin_registration_error():
    """Test that registering a duplicate plugin raises a ValueError."""
    from phenix_apps.apps.scale.registry import PluginRegistry

    registry = PluginRegistry()

    @registry.register_plugin("dup_test", "1.0")
    class P1:
        pass

    with pytest.raises(ValueError, match="is already registered"):
        @registry.register_plugin("dup_test", "1.0")
        class P2:
            pass


def test_registry_semantic_versioning():
    """Test that the registry correctly resolves semantic versions."""
    from phenix_apps.apps.scale.registry import PluginRegistry

    registry = PluginRegistry()

    @registry.register_plugin("semver_test", "1.2.0")
    class P1:
        pass

    @registry.register_plugin("semver_test", "1.10.0")
    class P2:
        pass

    @registry.register_plugin("semver_test", "1.9.0")
    class P3:
        pass

    # String sort would pick 1.9.0 (since '9' > '1' in '1.10.0')
    # Semantic sort should pick 1.10.0 (since 10 > 9)
    instance = registry.get_plugin("semver_test", "latest")
    assert isinstance(instance, P2)


def test_registry_deprecation_warning(caplog):
    """Test that retrieving a deprecated plugin logs a warning."""
    from phenix_apps.apps.scale.registry import PluginRegistry

    registry = PluginRegistry()

    @registry.register_plugin("dep_test", "1.0.0", deprecated=True)
    class P1:
        pass

    with caplog.at_level(logging.WARNING):
        registry.get_plugin("dep_test", "1.0.0")

    assert "Plugin 'dep_test' version '1.0.0' is deprecated" in caplog.text


def test_missing_plugin_error(mocker, mock_scale_app):
    """Test that requesting a missing plugin causes the app to exit."""
    mock_logger = mocker.patch("phenix_apps.apps.scale.app.logger")
    mock_exit = mocker.patch("sys.exit")

    app = mock_scale_app
    profile = {"name": "test", "plugin": "non_existent_plugin"}

    app._get_plugin_instance(profile)

    mock_exit.assert_called_with(1)
    mock_logger.error.assert_called()
    assert "Failed to load scale plugin 'non_existent_plugin'" in mock_logger.error.call_args[0][0]
