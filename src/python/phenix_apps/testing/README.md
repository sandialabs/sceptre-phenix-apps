# `phenix_apps.testing`

Pytest plugin for mocking `AppBase` subclasses. Auto-loads via the
[`pytest11`](https://docs.pytest.org/en/stable/how-to/writing_plugins.html#making-your-plugin-installable-by-others)
setuptools entry point group — pytest discovers and imports the plugin
automatically once `phenix-apps` is installed; no `conftest.py` wiring
or `-p` flag is needed.

| Fixture                | Purpose                                                          |
| ---------------------- | ---------------------------------------------------------------- |
| `mock_app`             | A partially-mocked instance of the class named in the marker     |
| `mock_fs`              | Dict of patched filesystem primitives (`open`, `makedirs`, ...)  |
| `_silence_phenix_log`  | Autouse, session — sets `settings.PHENIX_LOG_FILE = None`        |

```python
import pytest
from phenix_apps.apps.myapp.app import MyApp


@pytest.mark.app_class(cls=MyApp)
def test_does_thing(mock_app):
    mock_app.do_thing("host1")
    mock_app.add_inject.assert_called_once()
```

`cls` must be a kwarg — pytest treats classes passed positionally as the
decoration target. Other marker kwargs: `name`, `stage`, `dryrun`,
`real_methods=[...]` (leaves named methods un-mocked: defers to a subclass
override if one exists, otherwise binds the original `AppBase`
implementation). Apply module-wide via `pytestmark = ...`.

```python
import pytest
from phenix_apps.apps.myapp.app import MyApp

pytestmark = pytest.mark.app_class(cls=MyApp, name="myapp")


def test_one(mock_app): ...


def test_two(mock_app): ...
```

`mock_app` bypasses `__init__`, populates standard `AppBase` attributes
under `tmp_path`, and replaces every public `AppBase` method, including those
inherited from `ExperimentBase` (`extract_*`, `require_node`, `get_annotation`,
`mm_init`, `add_*`, `is_*`, `render`), with `MagicMock`s. An app that overrides
one of these and tests its own version must name it in `real_methods`.

App-specific attributes (e.g. Scale's `files_dir`) are not set — assign
them in the test if needed.

For non-marker flows, call `build_mock_app(cls, mocker, tmp_path, ...)`
directly.

## README examples

`phenix_apps.testing.readme` parses the YAML examples in a component README so
a test can validate them:

```python
from phenix_apps.testing.readme import readme_components

for component in readme_components(README, "qos"):
    parse_metadata(QoSMetadata, component["metadata"], component["name"])
```

`readme_yaml(readme, heading)` returns every parsed ```yaml block in a
`## heading` section; `readme_section(readme, heading)` returns its text.
