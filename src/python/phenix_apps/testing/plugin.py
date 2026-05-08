"""Pytest plugin providing fixtures for mocking AppBase subclasses.

Usage:

    import pytest
    from phenix_apps.apps.myapp.app import MyApp

    @pytest.mark.app_class(cls=MyApp)
    def test_something(mock_app):
        mock_app.do_thing("foo")
        mock_app.add_inject.assert_called_once()

The ``cls`` argument MUST be passed as a keyword. Passing a class positionally
makes pytest's mark machinery treat it as the decoration target.
"""

import os

import pytest
from box import Box

from phenix_apps.apps import AppBase
from phenix_apps.common import settings

# Methods on AppBase replaced with MagicMock on the instance so tests can
# assert calls without invoking real logic. Source of truth:
# phenix_apps/apps/__init__.py.
_APPBASE_METHODS = (
    "extract_app",
    "extract_node",
    "extract_node_interface_ip",
    "extract_node_hostname_for_ip",
    "extract_topology_nodes_by_attribute",
    "extract_annotated_topology_nodes",
    "extract_labelled_topology_nodes",
    "extract_app_node",
    "extract_all_nodes",
    "extract_nodes_type",
    "extract_nodes_label",
    "add_node",
    "add_inject",
    "add_annotation",
    "add_label",
    "get_annotation",
    "is_booting",
    "is_fully_scheduled",
    "render",
)

# Patched at class level so subclass overrides that call super().method(...)
# don't execute real logic.
_APPBASE_CLASS_PATCHES = (
    "add_inject",
    "add_annotation",
    "add_node",
    "add_label",
)

# Captured at import time, before any patching. Tests that opt into real
# behaviour for a method (via the marker's `real_methods` kwarg) get the
# unbound function from this dict re-bound to the mock instance.
_APPBASE_ORIGINALS = {name: getattr(AppBase, name) for name in _APPBASE_METHODS}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "app_class(cls=<AppClass>, name=..., stage=..., dryrun=..., "
        "real_methods=[...]): AppBase subclass to mock for the `mock_app` "
        "fixture. `cls` MUST be a kwarg. Other kwargs override defaults: "
        "name (cls.__name__.lower()), stage ('configure'), dryrun (True). "
        "real_methods is a list of AppBase methods to leave un-mocked on "
        "the instance (the original implementation is rebound).",
    )


@pytest.fixture(scope="session", autouse=True)
def _silence_phenix_log():
    """Disable file logging across the test session."""
    settings.PHENIX_LOG_FILE = None


@pytest.fixture
def mock_app(request, mocker, tmp_path):
    """Return a partially-mocked AppBase subclass instance.

    The class to instantiate is supplied via the ``@pytest.mark.app_class``
    marker. ``__init__`` is bypassed and standard attributes (exp_dir,
    app_dir, metadata, experiment, ...) are set with defaults rooted at
    ``tmp_path``. AppBase extension methods (``extract_*``, ``add_*``, etc.)
    are replaced with ``MagicMock`` instances on the instance.
    """
    marker = request.node.get_closest_marker("app_class")
    if marker is None or "cls" not in marker.kwargs:
        pytest.fail(
            "the `mock_app` fixture requires "
            "`@pytest.mark.app_class(cls=<AppClass>)` on the test or test class",
            pytrace=False,
        )

    app_cls = marker.kwargs["cls"]
    name = marker.kwargs.get("name", app_cls.__name__.lower())
    stage = marker.kwargs.get("stage", "configure")
    dryrun = marker.kwargs.get("dryrun", True)
    real_methods = marker.kwargs.get("real_methods", ())

    return build_mock_app(
        app_cls,
        mocker,
        tmp_path,
        name=name,
        stage=stage,
        dryrun=dryrun,
        real_methods=real_methods,
    )


def build_mock_app(
    app_cls,
    mocker,
    tmp_path,
    *,
    name=None,
    stage="configure",
    dryrun=True,
    real_methods=(),
):
    """Construct a mocked instance of ``app_cls`` for tests.

    Exposed for callers that build a mock app outside the marker flow (e.g.
    parametrized fixtures). Most tests should use the ``mock_app`` fixture.
    """
    if name is None:
        name = app_cls.__name__.lower()

    subclass_overrides = set()
    for cls in app_cls.__mro__:
        if cls in (AppBase, object):
            continue
        subclass_overrides.update(m for m in _APPBASE_METHODS if m in cls.__dict__)

    mocker.patch.object(app_cls, "__init__", return_value=None)
    for method in _APPBASE_CLASS_PATCHES:
        mocker.patch.object(AppBase, method)

    app = app_cls(name, stage, dryrun=dryrun)

    app.name = name
    app.stage = stage
    app.dryrun = dryrun
    app.raw_input = ""
    app.exp_name = "test_exp"
    app.exp_dir = str(tmp_path)
    app.app_dir = str(tmp_path / name)
    app.asset_dir = None
    app.metadata = Box({})
    app.topo = None
    app.app = Box({})
    app.templates_dir = str(tmp_path / "templates")
    app.experiment = Box(
        {"spec": {"topology": {"nodes": []}, "scenario": {"apps": []}}}
    )

    os.makedirs(app.app_dir, exist_ok=True)

    real_methods = set(real_methods)
    for method in _APPBASE_METHODS:
        if method in real_methods:
            if method in subclass_overrides:
                continue
            setattr(app, method, _APPBASE_ORIGINALS[method].__get__(app))
        else:
            setattr(app, method, mocker.MagicMock(name=f"{name}.{method}"))

    return app


@pytest.fixture
def mock_fs(mocker):
    """Patch common file-system primitives.

    Returns a dict keyed by primitive name so individual mocks can be
    inspected per-test.
    """
    return {
        "makedirs": mocker.patch("os.makedirs"),
        "open": mocker.patch("builtins.open", new_callable=mocker.mock_open),
        "isfile": mocker.patch("os.path.isfile", return_value=False),
        "isdir": mocker.patch("os.path.isdir", return_value=False),
        "rmtree": mocker.patch("shutil.rmtree"),
    }
