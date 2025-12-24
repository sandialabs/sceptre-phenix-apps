"""
Unit tests for the Scale logic and plugin compliance.
"""

import importlib
import pkgutil
from unittest.mock import MagicMock, mock_open, patch

import pytest
from box import Box

import phenix_apps.apps.scale.plugins
from phenix_apps.apps.scale.app import Scale
from phenix_apps.apps.scale.interface import ScalePlugin
from phenix_apps.apps.scale.plugins.builtin import BuiltinConfig, BuiltinV1
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


@patch("phenix_apps.apps.scale.app.os.makedirs")
def test_plugin_loading_builtin(_mock_makedirs):
    """Test that the builtin plugin is loaded by default."""
    with patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None):
        scale_app = Scale()
        scale_app.metadata = {}
        scale_app.exp_dir = "/tmp"
        scale_app.name = "scale"

        with patch("phenix_apps.apps.scale.app.get_plugin") as mock_get_plugin:
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
    with pytest.raises(ValueError):
        BuiltinConfig(**data)


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


@patch("phenix_apps.common.logger.log")
@patch("phenix_apps.apps.scale.app.Progress")
@patch("phenix_apps.apps.scale.app.minimega")
@patch("phenix_apps.apps.scale.app.utils")
def test_post_start_logic(_mock_utils, mock_minimega, _mock_progress, _mock_log):
    """Test post_start logic with mocked minimega and file operations."""
    mock_mm_conn = MagicMock()
    mock_minimega.connect.return_value = mock_mm_conn

    with patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None):
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
        with patch("builtins.open", mock_open()) as _:
            app.post_start()

            mock_minimega.connect.assert_called_with(namespace="test_exp")
            assert mock_mm_conn.cc_filter.call_count == 2
            assert mock_mm_conn.cc_send.call_count == 2
            mock_mm_conn.cc_filter.assert_any_call(filter="name=node-1")
            mock_mm_conn.cc_send.assert_any_call("/tmp/files/node-1.mm")


@patch("phenix_apps.common.logger.log")
def test_discover_plugins(_mock_log):
    """Test that _discover_plugins method correctly imports modules based on metadata."""
    with patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None):
        app = Scale()
        # Mock get_profiles to return profiles with specific plugins
        app.get_profiles = MagicMock(
            return_value=[{"plugin": "builtin"}, {"plugin": {"name": "wind"}}]
        )

        # Patch PLUGIN_REGISTRY to be empty so imports are attempted
        with (
            patch("phenix_apps.apps.scale.app.PLUGIN_REGISTRY", {}),
            patch("phenix_apps.apps.scale.app.entry_points", return_value=[]),
            patch("phenix_apps.apps.scale.app.importlib.import_module") as mock_import,
        ):
            app._discover_plugins()

            mock_import.assert_any_call("phenix_apps.apps.scale.plugins.builtin")
            mock_import.assert_any_call("phenix_apps.apps.scale.plugins.wind")


@patch("phenix_apps.apps.scale.app.os.makedirs")
def test_configure_adds_nodes_to_topology(_mock_makedirs):
    """Test that configure method adds nodes to the experiment topology."""
    with patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None):
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
