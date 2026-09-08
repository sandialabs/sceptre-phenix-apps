"""Unit tests for the mgmt_tap app."""

import pytest
from box import Box

from phenix_apps.apps.mgmt_tap.app import MgmtTap

pytestmark = pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap")


def _configure(mock_app, metadata=None, spec=None):
    """Set the metadata / experiment spec that _get_bridge() reads."""
    mock_app.metadata = metadata if metadata is None else Box(metadata)
    mock_app.experiment = Box({"spec": spec or {}})
    return mock_app


# --- Bridge resolution -------------------------------------------------------


def test_metadata_bridge_takes_precedence(mock_app):
    """An explicit bridge in app metadata wins over the experiment default."""
    app = _configure(mock_app, {"bridge": "metabr"}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "metabr"


def test_falls_back_to_experiment_default_bridge(mock_app):
    """With no metadata bridge, the experiment's defaultBridge is used."""
    app = _configure(mock_app, {}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


def test_falls_back_to_phenix_when_no_default_bridge(mock_app):
    """Neither metadata nor spec set a bridge, so the built-in default applies."""
    app = _configure(mock_app, {}, {})
    assert app._get_bridge() == MgmtTap.DEFAULT_BRIDGE == "phenix"


@pytest.mark.parametrize("empty", ["", None])
def test_empty_metadata_bridge_is_ignored(mock_app, empty):
    """A blank bridge value must not shadow the experiment default."""
    app = _configure(mock_app, {"bridge": empty}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


def test_absent_metadata_is_tolerated(mock_app):
    """metadata may be None/empty; resolution must not raise."""
    app = _configure(mock_app, None, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


# --- Bridge is threaded into the minimega command ----------------------------


def test_post_start_uses_resolved_bridge(mock_app, mocker):
    """The resolved bridge is what actually lands in the `tap create` command."""
    app = _configure(mock_app, {"bridge": "metabr"}, {"defaultBridge": "expbr"})
    app.bridge = app._get_bridge()
    app.vlan = "MGMT"
    app.subnet = None
    app.tap = "testexp_test"
    app.hosts = ["host1"]
    app.experiment.status = Box({"vlans": {"MGMT": 101}})

    mocker.patch.object(MgmtTap, "_get_mm_connection", return_value=mocker.MagicMock())
    compute_cmd = mocker.patch("phenix_apps.apps.mgmt_tap.app.mm_compute_cmd")

    app.post_start()

    command = compute_cmd.call_args.kwargs["command"]
    assert "bridge metabr" in command
    assert "bridge phenix" not in command
