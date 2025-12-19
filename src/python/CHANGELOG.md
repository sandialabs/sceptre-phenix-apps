# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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