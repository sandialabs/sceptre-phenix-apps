import importlib
import logging
import pkgutil
from unittest.mock import MagicMock

import pytest
from loguru import logger

import phenix_apps.apps.scale.plugins


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Dynamically discover and load all plugins once for all tests."""
    if hasattr(phenix_apps.apps.scale.plugins, "__path__"):
        for _, name, _ in pkgutil.iter_modules(phenix_apps.apps.scale.plugins.__path__):
            try:
                importlib.import_module(f"phenix_apps.apps.scale.plugins.{name}")
            except Exception:
                # Fail gracefully if a plugin can't be imported,
                # the compliance test will catch it.
                pass


@pytest.fixture(autouse=True)
def caplog_loguru_sink(caplog):  # noqa: ARG001
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
