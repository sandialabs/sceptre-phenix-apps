from unittest.mock import MagicMock

import pytest

from phenix_apps.apps import AppBase
from phenix_apps.testing.plugin import _APPBASE_METHODS, build_mock_app


class _DummyApp(AppBase):
    def __init__(self, name, stage, dryrun=False):
        super().__init__(name, stage, dryrun)


@pytest.mark.app_class(cls=_DummyApp)
def test_mock_app_default_attributes(mock_app, tmp_path):
    assert isinstance(mock_app, _DummyApp)
    assert mock_app.name == "_dummyapp"
    assert mock_app.stage == "configure"
    assert mock_app.dryrun is True
    assert mock_app.exp_name == "test_exp"
    assert mock_app.exp_dir == str(tmp_path)
    assert mock_app.app_dir == str(tmp_path / "_dummyapp")
    assert mock_app.experiment.spec.topology.nodes == []
    assert mock_app.experiment.spec.scenario.apps == []


@pytest.mark.app_class(cls=_DummyApp, name="custom", stage="cleanup", dryrun=False)
def test_mock_app_marker_overrides(mock_app, tmp_path):
    assert mock_app.name == "custom"
    assert mock_app.stage == "cleanup"
    assert mock_app.dryrun is False
    assert mock_app.app_dir == str(tmp_path / "custom")


@pytest.mark.app_class(cls=_DummyApp)
def test_mock_app_creates_app_dir_on_disk(mock_app):
    import os

    assert os.path.isdir(mock_app.app_dir)


@pytest.mark.app_class(cls=_DummyApp)
def test_mock_app_extension_methods_are_mocks(mock_app):
    for method in _APPBASE_METHODS:
        assert isinstance(getattr(mock_app, method), MagicMock), (
            f"expected {method} to be MagicMock"
        )

    mock_app.add_inject("host1", {"src": "/a", "dst": "/b"})
    mock_app.add_inject.assert_called_once_with("host1", {"src": "/a", "dst": "/b"})


@pytest.mark.app_class(cls=_DummyApp, real_methods=["add_node"])
def test_real_methods_marker_unmocks_method(mock_app):
    assert not isinstance(mock_app.add_node, MagicMock)

    mock_app.add_node({"general": {"hostname": "h1"}})

    assert len(mock_app.experiment.spec.topology.nodes) == 1
    assert mock_app.experiment.spec.topology.nodes[0].general.hostname == "h1"


class _OverridingApp(AppBase):
    def __init__(self, name, stage, dryrun=False):
        super().__init__(name, stage, dryrun)
        self.calls = []

    def add_inject(self, hostname, inject):
        self.calls.append((hostname, inject))
        super().add_inject(hostname, inject)


@pytest.mark.app_class(cls=_OverridingApp, real_methods=["add_inject"])
def test_real_methods_defers_to_subclass_override(mock_app, mocker):
    mock_app.calls = []
    mock_super = mocker.patch("phenix_apps.apps.AppBase.add_inject")

    mock_app.add_inject("h1", {"src": "a", "dst": "b"})

    assert mock_app.calls == [("h1", {"src": "a", "dst": "b"})]
    mock_super.assert_called_once_with("h1", {"src": "a", "dst": "b"})


def test_build_mock_app_helper_callable_directly(mocker, tmp_path):
    app = build_mock_app(_DummyApp, mocker, tmp_path, name="direct")

    assert app.name == "direct"
    assert app.app_dir == str(tmp_path / "direct")
    assert isinstance(app.extract_node, MagicMock)


def test_mock_fs_returns_expected_patches(mock_fs):
    assert set(mock_fs) == {"makedirs", "open", "isfile", "isdir", "rmtree"}

    assert mock_fs["isfile"]("/anywhere") is False
    assert mock_fs["isdir"]("/anywhere") is False

    mock_fs["isfile"].assert_called_once_with("/anywhere")


def test_mock_app_without_marker_fails_clearly(mocker, tmp_path):
    from phenix_apps.testing.plugin import mock_app as mock_app_fixture

    fn = mock_app_fixture._get_wrapped_function()

    request = mocker.Mock()
    request.node.get_closest_marker.return_value = None

    with pytest.raises(pytest.fail.Exception, match=r"@pytest\.mark\.app_class"):
        fn(request, mocker, tmp_path)
