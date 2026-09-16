# AGENTS.md

## Scope

These instructions apply to the entire repository. A more deeply nested
`AGENTS.md`, if one is added later, takes precedence for files in its subtree.

## Project Overview

SCEPTRE phēnix Apps contains the official applications, schedulers, Scale
plugins, and SCORCH components used by
[phēnix](https://github.com/sandialabs/sceptre-phenix), the cyber-experiment
orchestration platform. The repository is split into:

- `src/python/`: Python 3.12 package containing most apps, the single-node
  scheduler, shared minimega and logging helpers, Scale plugins, SCORCH
  components, and pytest support.
- `src/go/`: Go 1.24 module containing the `phenix-app-mirror` application and
  shared Go helpers.
- `debian/`: top-level Debian package assembly.
- `.github/workflows/`: path-scoped Python, Go, spelling, and repository
  dispatch automation.

The root `Makefile` delegates development commands to both language projects.
There is no long-running development server in this repository.

## phēnix Domain and Upstream Authority

This guide follows the cross-repository guidance introduced by the core
repository's
[`AGENTS.md` proposal in PR #386](https://github.com/sandialabs/sceptre-phenix/pull/386).
Before changing the app protocol, lifecycle behavior, experiment resource
shape, minimega integration, or SCORCH behavior, consult:

- The core repository's linked agent guidance and
  [`skills/phenix/SKILL.md`](https://github.com/sandialabs/sceptre-phenix/blob/main/skills/phenix/SKILL.md).
- Core app execution code under
  [`src/go/app/`](https://github.com/sandialabs/sceptre-phenix/tree/main/src/go/app).
- Versioned resource definitions under
  [`src/go/types/version/`](https://github.com/sandialabs/sceptre-phenix/tree/main/src/go/types/version).
- The online [Apps documentation](https://phenix.sceptre.dev/latest/apps/).

The implementation is the final authority when documentation and code differ.
Coordinate incompatible contract or resource-shape changes with the core
repository.

Related repositories:

- [`sceptre-phenix`](https://github.com/sandialabs/sceptre-phenix): core CLI,
  API, web UI, app runner, experiment models, and orchestration behavior.
- [`sceptre-phenix-docs`](https://github.com/sandialabs/sceptre-phenix-docs):
  source for the official narrative documentation.
- [`sceptre-phenix-images`](https://github.com/sandialabs/sceptre-phenix-images):
  image definitions, overlays, and scripts used by `phenix image`.
- [`sceptre-phenix-topologies`](https://github.com/sandialabs/sceptre-phenix-topologies):
  example topologies and disk images.
- [`minimega`](https://github.com/sandia-minimega/minimega): implementation of
  the distributed VM and network emulation platform used by phēnix. Consult its
  [API documentation](https://sandia-minimega.github.io/) before changing
  generated minimega commands.

## Architecture and Source Map

### Python

- `src/python/pyproject.toml` is the source of truth for package metadata,
  dependencies, console scripts, Scale plugin entry points, pytest plugin
  registration, Ruff settings, and package data.
- `src/python/phenix_apps/apps/__init__.py` defines `AppBase`, the standard app
  lifecycle, experiment helpers, topology mutation helpers, and template
  rendering.
- `src/python/phenix_apps/apps/<app>/` contains each app implementation and,
  where applicable, `__main__.py`, templates, tests, and app-specific
  documentation. Before changing an app or related code, read its local
  `README.md` when present; otherwise use the implementation, tests, root
  `README.md`, and official Apps documentation as the references.
- `src/python/phenix_apps/common/` contains shared settings, structured logging,
  minimega helpers, and error types. Reuse these helpers rather than duplicating
  protocol or command handling.
- `src/python/phenix_apps/apps/scale/` contains the Scale app, plugin interface,
  registry, built-in plugins, and colocated tests. Read
  `src/python/phenix_apps/apps/scale/README.md` before modifying the Scale app
  or writing or changing a Scale plugin.
- `src/python/phenix_apps/apps/scorch/` contains `ComponentBase` and individual
  SCORCH components. Component console scripts are registered separately in
  `pyproject.toml`. Before changing a component or related code, read its
  `src/python/phenix_apps/apps/scorch/<component>/README.md`.
- `src/python/phenix_apps/schedulers/` contains scheduler interfaces and the
  `single-node` scheduler.
- `src/python/phenix_apps/testing/` is an auto-loaded pytest plugin providing
  `mock_app`, `mock_fs`, and `build_mock_app`.

### Go

- `src/go/cmd/phenix-app-mirror/` contains the mirror app, embedded templates,
  metadata types, utilities, and tests. Read its `README.md` before changing
  mirror behavior or metadata.
- `src/go/util/` contains experiment decoding, dry-run, logging, scheduling,
  randomization, and template helpers.
- `src/go/go.mod` pins the phēnix core module through a `replace` directive.
  Review core API compatibility before changing that version.

### Bundled Runtime Data

The SCEPTRE app includes configuration tables, SunSpec XML models, and the
MyDesigner template tree. SCORCH also contains scripts and binary payloads.
Treat these as runtime package data:

- Do not modify anything under
  `src/python/phenix_apps/apps/sceptre/protocols/sunspec/`; leave the entire
  directory as-is.
- Do not reformat, regenerate, or replace bundled third-party and binary assets
  unless the task explicitly targets them.
- When adding runtime files, update `[tool.setuptools.package-data]` in
  `src/python/pyproject.toml` and verify the built wheel contains them.
- Keep Go files referenced by `//go:embed` in place and covered by build tests.

## Application Contracts

### phēnix Apps

Production apps must:

1. Accept exactly one lifecycle stage as the first positional argument.
2. Read the experiment document from standard input.
3. Write the updated experiment as valid JSON to standard output.
4. Write operational logs as newline-delimited structured JSON to standard
   error, or to the path selected by `PHENIX_LOG_FILE`.
5. Exit nonzero after surfacing invalid input or an operational failure.

The valid app stages are `configure`, `pre-start`, `post-start`, `running`, and
`cleanup`. `AppBase` accepts JSON and also accepts YAML for local dry runs, but
the core-facing interchange format is JSON. Never print progress, diagnostics,
or debug data to stdout because it corrupts the experiment stream.

Python apps should subclass `AppBase`, implement only required stage methods,
and use the standard entry point:

```python
from .app import MyApp


def main():
    MyApp.main("my-app")
```

Stage implementations should raise a specific exception instead of calling
`sys.exit()` or swallowing errors. `AppBase.execute_stage()` records the
traceback and converts failure to a nonzero exit. Use
`phenix_apps.common.logger.logger`; do not configure an independent logger.

Go apps should call `util.SetupLogging()`, use `log/slog` structured fields,
decode stdin through the shared experiment helpers, and reserve stdout for the
experiment JSON.

### SCORCH Components

SCORCH components subclass `ComponentBase` and use stages `configure`, `start`,
`stop`, and `cleanup`. Their process arguments are:

```text
<stage> <component_name> <run_id> <current_loop> <current_loop_count>
```

Components read experiment JSON from stdin and write their status artifact
below the SCORCH run directory. Raise exceptions from component logic so
`ComponentBase.execute_stage()` can capture logs, write the status file, and
report the failure. Use the shared logger and avoid direct stream replacement
outside the base class.

### Scale Plugins

Scale plugins implement `ScalePlugin`, validate profile data, and register
versioned implementations with `register_plugin`. Add the package to the
`phenix.scale.plugins` entry-point group in `pyproject.toml` so installed
packages discover it. Keep plugin versions semantic, document profile fields,
and test registry, validation, configure, and post-start behavior.

### Schedulers

Schedulers accept no positional arguments, read experiment JSON from stdin,
update scheduling fields, and write only the resulting JSON to stdout. Extend
`SchedulerBase` and register the console script in `pyproject.toml`.

## Prerequisites and Setup

Native development requires:

- Python 3.12 or newer, with pip 23 or newer.
- Go 1.24 or newer.
- GNU Make.
- `curl` to install the pinned `golangci-lint` version through the Makefile.
- Docker and Debian packaging tools only for packaging tasks.

Use a virtual environment so the Python Makefile's editable install remains
isolated:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
make install-dev
```

`make install-dev` installs `src/python` with development extras and installs
`golangci-lint` v2.11.3 into `$(go env GOPATH)/bin`. It requires network access.
For runtime dependencies only, use the language-specific targets:

```bash
make -C src/python install
make -C src/go install
```

The Go `install` target runs `go mod tidy`; review any resulting `go.mod` or
`go.sum` changes. Use `make help`, `make -C src/python help`, and
`make -C src/go help` to inspect supported targets.

## Development Workflow

Common root commands:

```bash
make check       # non-fixing Python and Go lint checks
make test        # Python and Go unit tests
make coverage    # Python coverage plus race-enabled Go coverage
make format      # mutates files with Ruff and golangci-lint formatters
make lint        # mutates files with supported lint and spelling fixes
make all         # format, lint, and test; also mutates files
make clean       # remove Python and Go build/test/lint artifacts
```

Prefer `make check && make test` for non-mutating pre-PR validation. Review the
diff after `make format`, `make lint`, or `make all`.

Run a Python app locally through the Scale dry-run helper:

```bash
make -C src/python dry-run \
  APP=scale \
  STAGE=configure \
  INPUT=phenix_apps/apps/scale/plugins/wind_turbine/tests/test_wind_turbine_input.yaml
```

The helper sets `PHENIX_LOG_FILE=""`, enables debug logging, adds `--dry-run`,
and redirects the input document to the selected `phenix-app-<name>` command.

## Testing and Validation

Use the narrowest relevant test first, then run the broader affected-language
checks.

Python:

```bash
make -C src/python test
make -C src/python test TEST=phenix_apps/apps/scale/tests/test_registry.py
make -C src/python coverage
make -C src/python check
```

- Tests are generally colocated in `tests/` below the implementation.
- For `AppBase` subclasses, prefer
  `@pytest.mark.app_class(cls=MyApp)` with the auto-loaded `mock_app` fixture.
  The class must be passed as a keyword argument.
- Use `real_methods=[...]` only for base methods whose real behavior is part of
  the test; app-specific attributes bypassed by `mock_app` must be set by the
  test.
- Golden files under the SCEPTRE app are intentional compatibility fixtures.
  Regenerate them with `PHENIX_UPDATE_GOLDEN=1` only when the expected behavior
  changed, then review the full diff.

Go:

```bash
cd src/go
go test ./cmd/phenix-app-mirror
go test ./...
make coverage
make check
```

`make -C src/go coverage` matches CI's race-enabled test path. Documentation
and other prose changes should also pass:

```bash
codespell --config .codespellrc AGENTS.md
```

There is no configured coverage threshold. Add or update focused tests for
behavior changes even when a broader test already exercises the path.

## Code and Design Conventions

- Follow `.editorconfig`: four spaces generally, tabs for Go and Makefiles, two
  spaces for YAML, LF line endings, and an 88-character Python line target.
- Python formatting and imports are owned by Ruff. Use double quotes and retain
  first-party imports under `phenix_apps`.
- Go formatting and lint policy are owned by `src/go/.golangci.yml`; do not
  bypass enabled linters without a narrow, justified exclusion.
- Reuse `AppBase`, `ComponentBase`, `SchedulerBase`, shared settings, shared
  errors, and utility functions before adding parallel abstractions.
- Keep console-script names, app names in scenario metadata, entry-point
  targets, package directories, and documentation synchronized.
- Preserve unknown experiment fields and existing topology/scenario data while
  making targeted mutations.
- Validate configuration early and include the app, component, host, or field
  in actionable error messages.
- Do not silently recover from invalid configuration or operational failures.
- Keep comments focused on non-obvious protocol, lifecycle, or domain logic.

## Runtime Configuration and Security

Common environment variables are defined in
`src/python/phenix_apps/common/settings.py` and the Go utilities:

- `PHENIX_LOG_FILE`: `stderr` for core JSON-log IPC, a path for standalone file
  logging, or an empty value for human-readable local/test output.
- `PHENIX_LOG_LEVEL`: logging threshold.
- `PHENIX_DRYRUN`: enables dry-run behavior.
- `PHENIX_DIR`, `PHENIX_TEMP_DIR`, `PHENIX_FILES_DIR`, `MM_FILEPATH`, and
  `MM_SOCKET_PATH`: runtime data and minimega locations.
- `PHENIX_STORE_ENDPOINT`: store endpoint used by the Go mirror app.
- `PHENIX_CC_*`: command-and-control polling and timeout controls.

Security requirements:

- Never commit credentials, tokens, signing keys, proprietary data, private
  images, real infrastructure details, or local environment files.
- Do not include secrets or full sensitive payloads in structured logs, status
  artifacts, fixtures, or exception text.
- Treat scenario metadata, file paths, templates, and command arguments as
  untrusted input. Validate before filesystem, subprocess, network, or
  minimega operations.
- Avoid shell command construction when argument-vector APIs are available.
- Preserve least-privilege workflow permissions and never print
  `REPO_DISPATCH_PAT` or other GitHub secrets.

## GitHub Actions CI

GitHub Actions is path scoped:

- `.github/workflows/python.yml` runs Python `make check` and `make test` for
  Python source changes.
- `.github/workflows/go.yml` runs Go `make check` and race-enabled coverage for
  Go source or module changes.
- `.github/workflows/codespell.yml` checks every pull request.
- `.github/workflows/dispatch.yml` sends an `apps-update` repository dispatch
  to `sceptre-phenix` after changes reach `main`.

Workflow path filters do not cover every build input. Run the relevant local
checks when changing `pyproject.toml`, Makefiles, templates, package data,
scripts, or documentation even if a language workflow does not trigger. Update
all affected filters when adding new source types or moving build inputs. Keep
action versions supported, caches tied to lock/module files, and local commands
aligned with CI.

## Build and Packaging

There is no root build target. Build Go binaries with:

```bash
cd src/go
./build.sh          # writes static Linux binaries below src/go/bin/
```

`debian/build.sh` assembles the top-level Debian package with
`fakeroot dpkg-deb`.

Packaging scripts may create artifacts and temporary metadata. Review and clean
those outputs before committing. Do not publish packages, push images, create
tags, or create releases.

## Documentation and Change Management

- Add user-visible code and behavior changes to `CHANGELOG.md` under
  `[Unreleased]` using the existing Keep a Changelog categories.
- Update the relevant app or component `README.md` when configuration,
  lifecycle behavior, dependencies, or examples change.
- Update `src/python/app_migration_guide.md` when the shared `AppBase` authoring
  pattern changes.
- Update console scripts, Scale plugin entry points, package-data declarations,
  tests, and docs together when adding or renaming an implementation.
- Changes to core contracts or public configuration may also require a paired
  pull request in `sceptre-phenix` or `sceptre-phenix-docs`; cross-link related
  pull requests.
- Use `.github/ISSUE_TEMPLATE/` for bug and feature reports and
  `.github/pull_request_template.md` for pull requests.

## Pull Request and Git Guidelines

- Use Conventional Commit messages: `type(scope): subject`.
- Name branches with a Conventional Commit type and short description, such as
  `feat-add-user-authentication`; branch names must not contain `/`.
- Use a rebase workflow and keep each logical feature in one coherent commit
  when practical.
- Keep pull request descriptions concise: state purpose, summarize relevant
  changes, link issues and companion-repository work, and list validation.
- Before requesting review, run checks for every affected area and report any
  command that could not be run.
- Perform a self-review and confirm no proprietary or sensitive information is
  present.
