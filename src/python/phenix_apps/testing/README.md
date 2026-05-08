# `phenix_apps.testing`

Pytest plugin for mocking `AppBase` subclasses. Auto-loads via the
`pytest11` entry point — installing `phenix-apps` is enough.

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

`mock_app` bypasses `__init__`, populates standard `AppBase` attributes
under `tmp_path`, and replaces extension methods (`extract_*`, `add_*`,
`is_*`, `render`, `get_annotation`) with `MagicMock`s.

App-specific attributes (e.g. Scale's `files_dir`) are not set — assign
them in the test if needed.

For non-marker flows, call `build_mock_app(cls, mocker, tmp_path, ...)`
directly.
