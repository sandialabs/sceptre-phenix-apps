# Go Instructions

Read the root [`AGENTS.md`](../../AGENTS.md) first, including its shared runtime
contracts. These rules apply to all work under `src/go/`.

## Source Map

- `cmd/phenix-app-mirror/`: the mirror app. `main.go` holds the stage dispatch
  and the `//go:embed templates/*` filesystem, `types.go` the metadata types,
  `util.go` the helpers, and `main_test.go` the tests. Read its
  [`README.md`](cmd/phenix-app-mirror/README.md) before changing mirror behavior
  or metadata.
- `util/`: shared helpers. `experiment.go` (`IsDryRun`, `DecodeExperiment`),
  `scenario.go` (scenario, app, node, and annotation extraction),
  `template.go` (rendering and embedded-asset restore), `logging.go`
  (`SetupLogging`), `headnode.go` (hostname-suffix trimming), `random.go`, and
  `slice.go`.
- `version/version.go`: the `Version` constant that the `version` pseudo-stage
  prints, alongside the VCS revision and build time read from the build info.
- `go.mod`: pins the phēnix core module through a `replace` directive. Review
  core API compatibility before changing that pseudo-version.
- `debian/`, `build.sh`, `docker-build.sh`: packaging.

## Contracts

- Call `util.SetupLogging()` first, then log through `log/slog` with structured
  key/value fields. It honors `PHENIX_LOG_FILE` the same way the Python logger
  does.
- Decode stdin with `util.DecodeExperiment` and reserve stdout for the
  experiment JSON. The `version` pseudo-stage is the one exception: it prints a
  version line and returns without reading stdin.
- `phenix-app-mirror` currently logs and returns on failure rather than exiting
  nonzero, so core cannot distinguish a failed stage from a no-op. Do not copy
  that pattern into new code, and prefer a nonzero exit when touching it.
- Keep files referenced by `//go:embed` in place, and keep them covered by a
  test that builds the embedded tree.

## Commands

Run from `src/go/`:

| Purpose | Command |
|---|---|
| Focused tests | `go test -race ./cmd/phenix-app-mirror` |
| All tests | `go test ./...` or `make test` |
| Race-enabled coverage, as CI runs it | `make coverage` |
| Non-fixing lint | `make check` |
| Format or fixing lint | `make format`, `make lint` |
| Install pinned `golangci-lint` v2.11.3 | `make install-dev` |
| Tidy modules | `make install` |
| Static Linux binaries into `bin/` | `./build.sh` |

## Conventions

- `.golangci.yml` and `gofmt` own formatting and lint policy. Go files and
  Makefiles use tabs.
- `nolintlint` is enabled with `require-specific` and `require-explanation`, so a
  suppression must name its linter and give a reason —
  `//nolint:wrapcheck // multierror already wraps errors`. Only `funlen`,
  `gocognit`, and `golines` may be suppressed without one. Prefer fixing the
  finding over suppressing it.
- Return operational and validation errors; never silently recover.
- Consult the [minimega API docs](https://sandia-minimega.github.io/) and
  [source](https://github.com/sandia-minimega/minimega) before changing code
  that constructs minimega commands or depends on minimega behavior.

## CI

`.github/workflows/go.yml` runs `make check` and `make coverage` here, but only
for `src/go/**.go`, `go.mod`, `go.sum`, and the workflow file. Changes to the
`Makefile`, `.golangci.yml`, templates, or packaging scripts fire no workflow;
run the checks locally. Keep the workflow's `GO_VERSION`, the `go.mod` directive,
and the pinned `golangci-lint` version aligned.
