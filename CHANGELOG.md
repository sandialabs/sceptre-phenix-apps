# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
- **Ignition App**: New app that configures an Inductive Automation Ignition Gateway 8.3 SCADA master

### Added
- **OT-sim App**: `fd-client` DNP3 masters use `helics.scan-rate` when it is set explicitly.
- **Ignition App**: Add linux support.
- **Ignition App**: Tags pick up the ot-sim devices and variables behind each DNP3 point (ex: `rtu/cap1/voltage`).
- **Ignition App**: DNP3 poll rate is configurable per class and outstation.
- **Ignition App**: Add support for sending DNP3 Analog Output setpoint control commands.
- **OT-sim App**: `points.Outstations` exposes the DNP3 points and listen endpoint of any outstation host for other apps; `Register` records its device, type, variable and protocol section.
- **Wind Turbine Scale Plugin**: Artifact-generation regression tests and documentation linking to the companion [complete example in sceptre-phenix-topologies](https://github.com/sandialabs/sceptre-phenix-topologies/tree/main/renewables/wind/wind-scale) (sandialabs/sceptre-phenix-apps#95).
- **SCEPTRE App**: Pre-flight scenario validation: one pydantic model, run before either stage, reporting every problem at once with the host and field.
- **SCEPTRE App**: Stage accounting in the logs: a scenario inventory by device type, and what each handler produced.
- **SCEPTRE App**: Files in `<assetDir>/injects/override/` that match no injection are reported as probable typos.
- **SCEPTRE App**: Test suite (128 tests), two of them characterization tests over both stages and all 310 infrastructure/device-type/protocol combinations, plus `apps/sceptre/README.md`.
- **SCORCH**: Pydantic metadata models for components (#160).
- **SCORCH**: `phenix-scorch-validate` checks component metadata.
- **SCORCH pipe**: Metadata model.
- **SCORCH disruption**: Metadata model with new margin, args, OS fields.
- **SCORCH hoststats**: Metadata model; failed samples are retried.

### Changed
- **OT-sim App**: DNP3 address assignment is a module function (`protocols.dnp3.assign_addresses`)
- **Build System**: mypy runs in `make check` and CI; modules with existing errors are listed in pyproject.toml.
- **Build System**: `Mako>=1.3.10`, `requests>=2.32.4` (security advisories).
- **Build System**: `lxml>=6.0.2`, the first release with wheels for Python 3.12 to 3.14.
- **SCEPTRE App**: Register numbering state is per `FieldDeviceConfig` instead of class-level mutable state on `Register`; numbering is no longer order-dependent across configs and the test suite runs safely in parallel. Output is unchanged.
- **SCEPTRE App**: `configure()` and `pre_start()` are stage classes, `ConfigureStage` and `PreStart`, sharing pre-start state through `PreStartState`.
- **SCEPTRE App**: The device-type table is `configs/infrastructures.yaml`; adding a device type needs no code change.
- **SCEPTRE App**: Injections are declared with `Sceptre.inject()`, and all of them in the configure stage.
- **Common**: `utils.abs_path()` always returns a `Path`.
- **SCEPTRE App**: Type annotations on every app function, `Final` on module constants.
- **SCEPTRE App**: Validation failures raise `error.AppError` instead of calling `sys.exit(1)`, matching the app contract.
- **SCEPTRE App**: `metadata.simulator` matches case-insensitively in both stages, as validation already did; a miscased name used to silently get the default config.
- **Build System**: `package-data` ships the `mydesigner` SCADA tree and infrastructure table.

### Removed
- **SCEPTRE App**: The `reg_config` manual register-map path. It was dead code: the app never populated it, so every device always took the automatic numbering branch. Output is unchanged.
- **SCEPTRE App**: SunSpec has been burned away by the SCORCHing heat of 3000 Suns and thus no longer exists in this repo.

### Fixed
- **Common Utils**: fix cc commands parsing to be resilient to header changes.
- **OT-sim App**: `fd-server` hosts ignored the app-level `infrastructure` setting, so their protocol registers didn't match the tags the I/O module published.
- **Common Utils**: `mm_exec_wait` and `mm_get_cc_responses` split `cc responses` output on whole header lines; stderr no longer swallows stdout, and output containing `/` is no longer truncated.
- **OT-sim App**: A DNP3 master without a configured `scan-rate` (FEPs without app-level `helics` metadata, and every `fd-client`) raised `AttributeError`. The `<scan-rate>` element is now omitted, so ot-sim uses its own default ([#72](https://github.com/sandialabs/sceptre-phenix-apps/issues/72)).
- **Common**: `connect_elastic()` raises instead of exiting silently.
- **Wind Turbine Scale Plugin**: Stage an optional `container_template.rootfs_source` on each generated VM outside the containers' shared weather volume; mount Node-RED flows at their configured container path. Reject densities that split a turbine's private network across VMs.
- **SCEPTRE App**: With more than one PowerWorld provider, only the last one's `hil_tags` reached the object list, and only the last one's `objects.txt` was written. Tags now aggregate across providers and every PowerWorld provider gets the combined `objects.txt`.
- **SCEPTRE App**: `fep` hosts raised `TypeError`, built without the required `device_subtype`.
- **SCEPTRE App**: Per-device register overrides raised `RuntimeError` in `SceptreMetadataParser`, which popped keys while iterating a live dict view.
- **SCEPTRE App**: A `power-transmission` inverter raised `TypeError`, passing `infrastructure` twice into `Device()`.
- **SCEPTRE App**: A `fep` without a mgmt interface raised `UnboundLocalError`, or reused the previous fep's endpoints.
- **SCORCH hoststats**: Stopping no longer loses final samples.
- **SCORCH hoststats**: Logs a one-line summary per sample, not full records.
- **SCEPTRE App**: A historian on a subnet with no OPC server was configured with an unrelated OPC's tag list and no address to collect from. It now gets no tags and a warning naming the subnet.
- **SCEPTRE App**: OPC, SCADA and historian configs now use case-insensitive matching of MGMT VLAN.
- **SCORCH pipe**: Unquoted mapping `data` broke the command; now rejected.
- **SCORCH pipe**: minimega expanded backslashes in `data`; they are now sent as written.
- **SCORCH disruption**: `start` no longer fails in an hour's last second.
- **SCORCH disruption**: `dos` waits for `start_delay` plus attack time.
- **SCORCH disruption**: MGMT interface matched in any case; too-long `start_delay` rejected.
- **SCORCH disruption**: Failed physical stages are all reported; short dos attacks warn.

### Security
- **Common**: New `validate_hostname()` (phenix v2026.10.02 rules) and `safe_join()` guard hostnames and paths built from metadata; `mm_send()`/`mm_recv()` stay inside the miniccc mount. **Breaking:** rejects `_`, 1-char, all-digit, `all` and `phenix` hostnames.
- **Apps**: Scale, wind turbine and Ignition names are restricted; protonuke and wireguard reject embedded newlines; wireguard configs are `0600`, sceptre startup scripts `0755`.
- **SCORCH**: `cc`, `ssh` and `providerdata` transfers stay inside the run directory.

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
