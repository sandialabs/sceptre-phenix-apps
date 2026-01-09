import importlib
import logging
import os
import pkgutil
from unittest.mock import MagicMock

import pytest
from box import Box
from loguru import logger

import phenix_apps.apps.scale.plugins
from phenix_apps.common import settings


@pytest.fixture(scope="session", autouse=True)
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

@pytest.fixture(autouse=True)
def caplog_loguru_sink(caplog):
    """
    Redirect loguru logs to the standard logging module so pytest's caplog can capture them.
    """
    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield
    logger.remove(handler_id)


@pytest.fixture
def mock_minimega(mocker):
    """Mock the minimega connection."""
    mock_mm = mocker.patch("phenix_apps.apps.scale.app.minimega")
    mock_conn = MagicMock()
    mock_mm.connect.return_value = mock_conn
    return mock_conn


@pytest.fixture
def mock_scale_app(mocker, tmp_path):
    """
    Return a Scale app instance with mocked init and temporary directories.
    """
    mocker.patch("phenix_apps.apps.scale.app.Scale.__init__", return_value=None)

    from phenix_apps.apps.scale.app import Scale

    app = Scale()
    app.name = "scale"
    app.exp_name = "test_exp"
    app.exp_dir = str(tmp_path)
    app.app_dir = str(tmp_path / "scale")
    app.files_dir = str(tmp_path / "images")
    app.templates_dir = str(tmp_path / "templates")
    app.metadata = {}
    app.dryrun = True
    app.experiment = Box({"spec": {"topology": {"nodes": []}, "scenario": {"apps": []}}})

    # Create directories so real file operations (if any) don't fail
    os.makedirs(app.app_dir, exist_ok=True)
    os.makedirs(app.files_dir, exist_ok=True)

    return app