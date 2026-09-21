# Python Instructions

Read the root [`AGENTS.md`](../../AGENTS.md) first, including its shared runtime
contracts. These rules apply to all work under `src/python/`.

## Source Map

- `pyproject.toml`: the source of truth for metadata, dependencies, console
  scripts, Scale plugin entry points, pytest plugin registration, Ruff, vulture,
  and package data.
- `phenix_apps/apps/__init__.py`: `AppBase`, the lifecycle, and the experiment,
  topology-mutation, and template-rendering helpers.
- `phenix_apps/apps/<app>/`: one app each, with `__main__.py`, templates, tests,
  and usually a `README.md`. Read that `README.md` before changing the app.
- `phenix_apps/apps/scale/`: the Scale app, `interface.py`, `registry.py`,
  built-in plugins, and colocated tests. Read
  [`apps/scale/README.md`](phenix_apps/apps/scale/README.md) before changing the
  app or any plugin.
- `phenix_apps/apps/scorch/`: `ComponentBase` in `app.py` plus one directory per
  SCORCH component, each with its own `README.md`.
- `phenix_apps/common/`: shared settings, structured logging, minimega helpers,
  and error types. Reuse these instead of re-implementing protocol or command
  handling.
- `phenix_apps/schedulers/`: `SchedulerBase` and the `single-node` scheduler.
- `phenix_apps/testing/`: the auto-loaded pytest plugin. See its
  [`README.md`](phenix_apps/testing/README.md).
- `app_migration_guide.md`: the `AppBase` authoring pattern; update it when that
  pattern changes.

## Component Contracts

### Apps

Subclass `AppBase`, implement only the stage methods the app needs, and use the
standard entry point:

```python
from .app import MyApp


def main():
    MyApp.main("my-app")
```

Raise a specific exception instead of calling `sys.exit()` or swallowing an
error; `AppBase.execute_stage()` records the traceback and exits nonzero. Use
`from phenix_apps.common.logger import logger`; never configure an independent
logger.

### SCORCH Components

Components subclass `ComponentBase`, use the stages `configure`, `start`,
`stop`, and `cleanup`, and take five positional arguments:

```text
<stage> <component_name> <run_id> <current_loop> <current_loop_count>
```

They read experiment JSON from stdin and write a status artifact below the
SCORCH run directory. Raise exceptions from component logic so
`ComponentBase.execute_stage()` can capture logs, write the status file, and
report the failure. Use the shared logger and do not replace streams outside the
base class. Register each component's console script in `pyproject.toml`.

### Scale Plugins

Plugins subclass `ScalePlugin` from `phenix_apps/apps/scale/interface.py`,
implement every abstract method, validate profile data in `validate_profile`,
and register with the `@register_plugin(name, version)` decorator from
`phenix_apps/apps/scale/registry.py`.
Add the package to the `phenix.scale.plugins` entry-point group in
`pyproject.toml` so installed packages discover it. Keep versions semantic, mark
superseded versions `deprecated=True`, document profile fields, and test
registry, validation, configure, and post-start behavior.

### Schedulers

Schedulers take no positional arguments, read experiment JSON from stdin, update
scheduling fields, and write only the resulting JSON to stdout. Extend
`SchedulerBase` and register the console script in `pyproject.toml`.

## Bundled Runtime Data

The SCEPTRE app ships configuration tables, SunSpec XML models, and the
MyDesigner template tree; Ignition ships a Jython 2.7 template tree; SCORCH
ships scripts and binary payloads. Treat all of it as runtime package data.

- Leave `phenix_apps/apps/sceptre/protocols/sunspec/` exactly as-is. It is
  excluded from Ruff and codespell for that reason.
- `phenix_apps/apps/ignition/templates/` is Jython 2.7 and is excluded from
  Ruff and vulture. Do not modernize it to Python 3 syntax.
- Do not reformat, regenerate, or replace bundled third-party or binary assets
  unless the task explicitly targets them.
- When adding a runtime file, add it to `[tool.setuptools.package-data]` in
  `pyproject.toml` and confirm the built wheel contains it.

## Commands

Run from `src/python/`:

| Purpose | Command |
|---|---|
| All tests | `make test` |
| One test file or node | `make test TEST=phenix_apps/apps/scale/tests/test_registry.py` |
| Coverage | `make coverage` |
| Non-fixing lint (ruff, codespell, vulture) | `make check` |
| Format or fixing lint | `make format`, `make lint` |
| Editable install, with dev extras | `make install`, `make install-dev` |

Dry-run an app locally:

```bash
make dry-run APP=scale STAGE=configure \
  INPUT=phenix_apps/apps/scale/plugins/wind_turbine/tests/test_wind_turbine_input.yaml
```

The target sets `PHENIX_LOG_FILE=""` and `PHENIX_LOG_LEVEL=debug`, appends
`--dry-run`, and pipes `INPUT` into `phenix-app-$(APP)`. It defaults to
`APP=scale` and `STAGE=post-start`, and rejects an invalid stage or a missing
input file.

## Testing

- Tests are colocated in a `tests/` directory below the implementation.
- For `AppBase` subclasses, prefer `@pytest.mark.app_class(cls=MyApp)` with the
  auto-loaded `mock_app` fixture. `cls` must be a keyword argument. Apply it
  module-wide with `pytestmark`.
- `mock_app` bypasses `__init__` and replaces the `extract_*`, `add_*`, `is_*`,
  `render`, and `get_annotation` helpers with mocks. Set app-specific attributes
  in the test yourself.
- Use `real_methods=[...]` only for base methods whose real behavior is under
  test. Use `build_mock_app()` directly for non-marker flows.
- Golden files under the SCEPTRE app are intentional compatibility fixtures.
  Regenerate with `PHENIX_UPDATE_GOLDEN=1` only when the expected behavior
  changed, then review the full diff.

## Conventions

- Ruff owns formatting and imports: double quotes, 88-column target, and
  first-party imports under `phenix_apps`. `E501` is ignored, so the formatter,
  not the linter, enforces line length.
- Target Python 3.12; the phēnix image ships `ubuntu:24.04`.
- `vulture` runs at `min_confidence = 80`. Delete dead code rather than adding a
  suppression, unless the symbol is a public entry point. It does not scan
  `phenix_apps/apps/__init__.py`, `phenix_apps/common/`, or the vendored template
  trees, so unused code there needs a manual read.

## CI

`.github/workflows/python.yml` runs `make check` and `make test` here, but only
for `src/python/**.py` and the workflow file. Run the checks locally after
changing `pyproject.toml`, the `Makefile`, templates, package data, or scripts,
because no workflow fires for those paths.
