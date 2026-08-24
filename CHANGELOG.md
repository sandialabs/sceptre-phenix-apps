# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **SCEPTRE App**: Pre-flight scenario validation: one pydantic model, run before either stage, reporting every problem at once with the host and field.
- **SCEPTRE App**: Stage accounting in the logs: a scenario inventory by device type, and what each handler produced.
- **SCEPTRE App**: Files in `<assetDir>/injects/override/` that match no injection are reported as probable typos.
- **SCEPTRE App**: Test suite (128 tests), two of them characterization tests over both stages and all 310 infrastructure/device-type/protocol combinations, plus `apps/sceptre/README.md`.

### Changed
- **SCEPTRE App**: `configure()` and `pre_start()` are stage classes, `ConfigureStage` and `PreStart`, sharing pre-start state through `PreStartState`.
- **SCEPTRE App**: The device-type table is `configs/infrastructures.yaml`; adding a device type needs no code change.
- **SCEPTRE App**: Injections are declared with `Sceptre.inject()`, and all of them in the configure stage.
- **SCEPTRE App**: Type annotations on every app function, `Final` on module constants.
- **SCEPTRE App**: Validation failures raise `error.AppError` instead of calling `sys.exit(1)`, matching the app contract.
- **SCEPTRE App**: `metadata.simulator` matches case-insensitively in both stages, as validation already did; a miscased name used to silently get the default config.
- **Build System**: `package-data` now ships the SunSpec models, the `mydesigner` SCADA tree and the infrastructure table; an installed wheel was missing all three.

### Fixed
- **SCEPTRE App**: `fep` hosts raised `TypeError`, built without the required `device_subtype`.
- **SCEPTRE App**: Per-device register overrides raised `RuntimeError` in `SceptreMetadataParser`, which popped keys while iterating a live dict view.
- **SCEPTRE App**: A `power-transmission` inverter raised `TypeError`, passing `infrastructure` twice into `Device()`.
- **SCEPTRE App**: A `fep` without a mgmt interface raised `UnboundLocalError`, or reused the previous fep's endpoints.
- **SCEPTRE App**: A historian on a subnet with no OPC server was configured with an unrelated OPC's tag list and no address to collect from. It now gets no tags and a warning naming the subnet.

## [2.0.0] - 2026-03-04

### Changed
- **Logging**: Updated `AppBase` to enforce the new App Contract, emitting structured JSON logs to `stderr` for aggregation by the Core daemon.
- **Error Handling**: `AppBase` now captures full tracebacks in a structured `traceback` field using `logger.exception` instead of printing raw text to stderr.
- **Scale App**: Disabled `rich` progress bars on stderr during production runs to prevent JSON log corruption.
- **Helics App**: Replaced `sys.exit(1)` with exceptions to ensure proper JSON error logging.
- **Scorch App**: Replaced `sys.exit(1)` with exceptions to ensure JSON status files are written on failure.
- **Scorch App**: Removed raw stdout/stderr printing. All logs now go to `stderr` as structured JSON.
- **Scorch App**: Fixed internal log capturing for status files by using a custom log sink instead of monkey-patching `logger.log`.
- **Build System**: Standardized Makefiles with consistent targets (`help`, `all`, `test`, `lint`, `format`, `clean`) and improved help output.
- **Mirror App**: Refactored `main.go` to reduce complexity and improve testability.
- **Mirror App**: Fixed linting errors and updated to use `log/slog` for structured logging.
- **Go**: Updated Go version requirement to 1.24.

## [1.0.0]

### Added
- **New `scale` Application**: A new Phenix app (`phenix-app-scale`) designed for high-volume, large-scale simulations using a plugin architecture.
- **`scale` App Plugins**:
  - **`builtin` Plugin**: For generic infrastructure scaling. Supports direct VM counts (`count`) and calculated VM counts based on container density (`containers` and `containers_per_node`).
  - **`wind_turbine` Plugin**: A domain-specific plugin to simulate wind farms using OT-Sim. It automatically generates the 6-container architecture for each turbine and handles all internal configuration (Modbus, DNP3, Logic).
- **Comprehensive Documentation**:
  - Added `README.md` files for the `scale` app and each of its plugins (`builtin`, `wind_turbine`).
  - Included diagrams to visualize application and plugin architectures.
  - Added detailed instructions for testing and performing dry-runs.
- **Unit and Integration Tests**:
  - Added extensive `pytest` tests for the new `scale` app and its plugins.
  - Added tests for the refactored `AppBase` class.
- **Makefile `dry-run` Target**: Added a new `make dry-run` target to easily test the `scale` app's configuration and post-start stages with sample input files.
- **Dev Dependencies**: Added `pytest-mock` to support advanced unit testing patterns.
- **Migration Guide**: Created `docs/app_migration_guide.md` to assist developers in updating existing apps to the new `AppBase` structure.

### Changed
- **`AppBase` Refactoring (Breaking Change)**:
  - The `AppBase.__init__` constructor now handles argument parsing and reading experiment data from `stdin`, simplifying app initialization.
  - A new `AppBase.main()` class method is now the standard entry point for all Phenix apps, reducing boilerplate code in `__main__.py` files.
  - All existing apps (`sceptre`, `wind_turbine`, etc.) have been updated to conform to this new pattern.

### Deprecated
- The standalone `phenix-app-wind-turbine` is now deprecated. All of its functionality has been migrated to the `scale` app's `wind_turbine` plugin, which offers superior scalability and configuration management.

## [0.2.0]

- Initial release with various applications including `sceptre`, `helics`, and `ot-sim`.