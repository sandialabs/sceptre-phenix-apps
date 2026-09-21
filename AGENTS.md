# AGENTS.md

## Project and Instruction Scope

SCEPTRE phēnix Apps holds the official apps, schedulers, Scale plugins, and
SCORCH components run by [phēnix](https://github.com/sandialabs/sceptre-phenix),
the cyber-experiment orchestration platform.

- `src/python/`: Python 3.12 package with most apps, the `single-node`
  scheduler, shared helpers, Scale plugins, SCORCH components, and an
  auto-loaded pytest plugin.
- `src/go/`: Go 1.24 module with the `phenix-app-mirror` app and shared helpers.
- `debian/`: top-level Debian package assembly.
- `.github/workflows/`: path-scoped Python, Go, spelling, and dispatch CI.

The root `Makefile` only delegates to the two language projects. There is no
root build target and no long-running development server.

Root rules apply everywhere. Before changing a scoped area, read its closer
instructions:

| Trigger | Required instructions |
|---|---|
| Any app, scheduler, Scale plugin, SCORCH component, or pytest work under `src/python/` | [`src/python/AGENTS.md`](src/python/AGENTS.md) |
| Any `phenix-app-mirror`, shared `util/`, or Go module work under `src/go/` | [`src/go/AGENTS.md`](src/go/AGENTS.md) |

The closest `AGENTS.md` adds area-specific rules; this file remains binding.

## phēnix Domain and Upstream Authority

`sceptre-phenix` owns the app protocol, lifecycle, experiment resource shape,
minimega integration, and SCORCH behavior. Read the relevant reference before
changing any of them:

| Need | Reference |
|---|---|
| Cross-repository agent rules | [`sceptre-phenix/AGENTS.md`](https://github.com/sandialabs/sceptre-phenix/blob/main/AGENTS.md) |
| phēnix CLI, API, and resource usage | [`skills/phenix/SKILL.md`](https://github.com/sandialabs/sceptre-phenix/blob/main/skills/phenix/SKILL.md) |
| How core runs apps | [`src/go/app/`](https://github.com/sandialabs/sceptre-phenix/tree/main/src/go/app) |
| Versioned resource definitions | [`src/go/types/version/`](https://github.com/sandialabs/sceptre-phenix/tree/main/src/go/types/version) |
| Narrative app documentation | [Apps docs](https://phenix.sceptre.dev/latest/apps/), source in [`sceptre-phenix-docs`](https://github.com/sandialabs/sceptre-phenix-docs) |
| minimega commands and behavior | [API docs](https://sandia-minimega.github.io/), [source](https://github.com/sandia-minimega/minimega) |
| Image configs, overlays, scripts | [`sceptre-phenix-images`](https://github.com/sandialabs/sceptre-phenix-images) |
| Example topologies and disk images | [`sceptre-phenix-topologies`](https://github.com/sandialabs/sceptre-phenix-topologies) |

Implementation is the final authority when code and documentation differ.
Coordinate incompatible contract or resource-shape changes with `sceptre-phenix`
and cross-link the pull requests.

## Runtime Contracts

Every production app, in either language, must:

1. Accept exactly one lifecycle stage as the first positional argument:
   `configure`, `pre-start`, `post-start`, `running`, or `cleanup`.
2. Read the experiment document from stdin.
3. Write the updated experiment as valid JSON to stdout, and nothing else.
   Progress, diagnostics, and debug output on stdout corrupt the stream.
4. Write newline-delimited structured JSON logs to stderr, or to the path in
   `PHENIX_LOG_FILE`.
5. Exit nonzero after surfacing invalid input or an operational failure.

JSON is the core-facing interchange format. Python `AppBase` also accepts YAML,
but only for local dry runs.

SCORCH components and schedulers use different argument shapes; see
[`src/python/AGENTS.md`](src/python/AGENTS.md).

## Setup and Common Commands

Requirements: Python 3.12+ with pip 23+, Go 1.24+, GNU Make, and `curl` (the Go
`install-dev` target downloads a pinned `golangci-lint`). Packaging work also
needs Docker and the Debian packaging tools.

Use a virtual environment so the editable install stays isolated:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
make install-dev   # editable install with dev extras, plus golangci-lint; needs network
```

| Purpose | Command |
|---|---|
| Inspect targets | `make help`, `make -C src/python help`, `make -C src/go help` |
| Non-fixing lint for both languages | `make check` |
| Unit tests for both languages | `make test` |
| Coverage (Python plus race-enabled Go) | `make coverage` |
| Format, fixing lint, or both plus tests | `make format`, `make lint`, `make all` |
| Remove build, test, and lint artifacts | `make clean` |
| Install without dev extras | `make -C src/python install` (editable), `make -C src/go install` (`go mod tidy`) |

`format`, `lint`, and `all` mutate files; review the diff afterwards. The Go
`install` target runs `go mod tidy`, so review any `go.mod` or `go.sum` change.

## Validation

Run the narrowest relevant test first, then the affected language's checks.
`make check && make test` is the non-mutating pre-PR sweep. Prose changes should
also pass `codespell --config .codespellrc <file>`.

There is no coverage threshold. Add focused tests for behavior changes even when
a broader test already covers the path. Report any check you could not run.

## Conventions

- Follow `.editorconfig`: four spaces by default, tabs for Go and Makefiles, two
  spaces for YAML, LF endings, and an 88-character Python line target. `.ps1` and
  `.bat` files use CRLF; `src/python/phenix_apps/apps/scorch/opcexport/` ships
  one, so do not normalize its endings.
- Reuse `AppBase`, `ComponentBase`, `SchedulerBase`, shared settings, shared
  errors, and `util` helpers before adding parallel abstractions.
- Keep console-script names, app names in scenario metadata, entry-point
  targets, package directories, and documentation synchronized.
- Preserve unknown experiment fields and existing topology and scenario data
  while making targeted mutations.
- Validate configuration early. Name the app, component, host, or field in error
  messages. Never silently recover from invalid configuration or a failure.
- Keep comments on non-obvious protocol, lifecycle, or domain logic only.

## Runtime Configuration and Security

Most environment variables are read in
`src/python/phenix_apps/common/settings.py`:

| Variable | Meaning |
|---|---|
| `PHENIX_LOG_FILE` | `stderr` for core JSON-log IPC, a path for standalone file logging, empty for human-readable local output. Defaults to `/var/log/phenix/phenix-apps.log`, so local runs normally clear it |
| `PHENIX_LOG_LEVEL` | Logging threshold, default `INFO` |
| `PHENIX_DIR`, `PHENIX_TEMP_DIR` | phēnix data and scratch directories |
| `MM_FILEPATH`, `MM_SOCKET_PATH` | minimega file root and command socket |
| `PHENIX_CC_*` | miniccc polling rates and timeout grace periods |

Read elsewhere: `PHENIX_DRYRUN` (literal `true`) in
`src/python/phenix_apps/apps/__init__.py`,
`src/python/phenix_apps/apps/scorch/app.py`, and `src/go/util/experiment.go`;
`PHENIX_FILES_DIR` in `src/python/phenix_apps/apps/scorch/app.py`;
`PHENIX_STORE_ENDPOINT` in `src/go/cmd/phenix-app-mirror/main.go`.

Security requirements:

- Never commit credentials, tokens, signing keys, proprietary data, private
  images, real infrastructure details, or local environment files.
- Keep secrets and full sensitive payloads out of structured logs, status
  artifacts, fixtures, and exception text.
- Treat scenario metadata, file paths, templates, and command arguments as
  untrusted. Validate before filesystem, subprocess, network, or minimega calls.
- Avoid shell string construction when an argument-vector API exists.
- Preserve least-privilege workflow permissions. Never print
  `REPO_DISPATCH_PAT` or another GitHub secret.

## GitHub Actions CI

| Workflow | Trigger | Runs |
|---|---|---|
| `python.yml` | `src/python/**.py` or the workflow file | `make check`, `make test` in `src/python` |
| `go.yml` | `src/go/**.go`, `go.mod`, `go.sum`, or the workflow file | `make check`, `make coverage` in `src/go` |
| `codespell.yml` | Every pull request | `codespell` with `.codespellrc` |
| `dispatch.yml` | Push to `main`, `sandialabs` only | `apps-update` repository dispatch to `sceptre-phenix` |

Path filters do not cover every build input. Run the relevant local checks after
changing `pyproject.toml`, a `Makefile`, templates, package data, scripts, or
documentation, even when no language workflow fires. Update every affected
filter when adding a source type or moving a build input. Keep action versions
supported, caches tied to lock or module files, and local commands aligned with
CI.

## Build and Packaging

`src/go/build.sh` writes static Linux binaries into `src/go/bin/`.
`debian/build.sh` assembles the top-level package with `fakeroot dpkg-deb`.
`src/go/debian/` holds the Go package layout, and `src/go/docker-build.sh`
builds it in a container.

Packaging scripts leave artifacts and temporary metadata behind; review and
clean them before committing. Do not publish packages, push images, create tags,
or create releases.

## Change Management

- Record user-visible code and behavior changes in `CHANGELOG.md` under
  `[Unreleased]`, using the existing Keep a Changelog categories.
- Update the app or component `README.md` when configuration, lifecycle
  behavior, dependencies, or examples change.
- Update `src/python/app_migration_guide.md` when the `AppBase` authoring
  pattern changes.
- When adding or renaming an implementation, update console scripts, entry
  points, package-data declarations, tests, and docs together.
- Core-contract or public-configuration changes may need a paired pull request
  in `sceptre-phenix` or `sceptre-phenix-docs`; cross-link them.
- Follow [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) and use the
  templates under `.github/`.

## Pull Requests and Git

- Use Conventional Commit messages: `type(scope): subject`.
- Branch names start with a Conventional Commit type, use a short description,
  and must not contain `/`, for example `feat-add-user-authentication`.
- Use a rebase workflow and keep one coherent commit per logical change.
- Keep pull request descriptions concise: purpose, relevant changes, linked
  issues and companion pull requests, and the validation you ran.
- Self-review before requesting review and confirm no proprietary or sensitive
  information is present.
