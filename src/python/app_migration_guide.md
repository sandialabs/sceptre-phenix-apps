# Migration Guide: Updating to the new AppBase Structure

The `AppBase` class has been refactored to standardize application initialization and reduce boilerplate code in individual apps. This guide provides the necessary steps to update your existing Phenix apps to the new structure.

## Summary of Changes

1.  **`AppBase.__init__`**: The base class constructor now handles argument parsing, reading `stdin`, and initializing core attributes like `self.experiment`, `self.stage`, and `self.dryrun`.
2.  **`AppBase.main()`**: A new class method that serves as the standard entry point for all apps. It manages the entire lifecycle from argument parsing to final JSON output.

## Step 1: Update the `__main__.py` Entry Point

The app's entry point file becomes much simpler. You no longer need to handle `argparse` or instantiate the class manually.

### Before

The old entry point typically looked like this, with manual argument parsing and app instantiation.

```python
# old __main__.py
import argparse
import sys
from .app import MyApp

def main():
    parser = argparse.ArgumentParser(description="phenix user app: my-app")
    parser.add_argument("stage", choices=["configure", "pre-start", ...], help="Lifecycle stage")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run")
    args = parser.parse_args()

    app = MyApp(args.stage, args.dry_run)
    app.execute_stage()
    print(app.experiment.to_json())

if __name__ == "__main__":
    main()
```

### After

Update the file to call the new `AppBase.main()` class method, passing the app's registered name.

```python
# new __main__.py
from .app import MyApp

def main():
    MyApp.main("my-app-name")

if __name__ == "__main__":
    main()
```

## Step 2: Update the App's `__init__` Method

The constructor for your app's main class needs to be updated to accept the new arguments and call the superclass constructor. You can remove all the boilerplate code that is now handled by `AppBase`.

### Before

The old constructor was responsible for reading `stdin`, parsing the experiment data, and setting up initial attributes.

```python
# old app.py
import sys
from box import Box
from phenix_apps.apps import AppBase

class MyApp(AppBase):
    def __init__(self, stage, dryrun=False):
        self.raw_input = sys.stdin.read()
        self.experiment = Box.from_json(self.raw_input)
        self.stage = stage
        self.dryrun = dryrun
        # ... other app-specific initialization
```

### After

The new constructor is much cleaner. It accepts `name`, `stage`, and `dryrun` and immediately passes them to `super().__init__()`. All the core attributes are set by the base class.

```python
# new app.py
from phenix_apps.apps import AppBase

class MyApp(AppBase):
    def __init__(self, name, stage, dryrun=False):
        super().__init__(name, stage, dryrun)
        # self.experiment, self.stage, self.dryrun, self.app, etc.
        # are now available from the super constructor.

        # ... other app-specific initialization can go here
```

# Migrating Wind Turbine App to Scale Plugin

The standalone `wind-turbine` app has been deprecated in favor of the `wind_turbine` plugin for the `scale` app. This shift moves from manually defining topology nodes (or using complex regex patterns) to a declarative model where you simply state the number of turbines desired.

## Key Changes

1.  **App Name**: Change `name: wind-turbine` to `name: scale`.
2.  **Topology Generation**: You no longer define `hosts` in the app metadata. The plugin generates the topology automatically.
3.  **Scaling**: Instead of listing hosts or using regex, use the `count` parameter to specify the number of turbines.
4.  **Density**: Use `containers_per_node` to control how many turbine components are packed onto a single VM.
5.  **Networking**: Define the external network CIDR in `container_template`. The plugin handles IP assignment.
6.  **Variable Substitution**: Regex group substitutions (e.g., `$1`) in HELICS topics are replaced with Jinja2-style placeholders (e.g., `{{turbine_name}}`).

## Example Migration

### Before (Old App)

The old app required defining templates and then mapping them to hosts, often using complex regex to link components.

```yaml
spec:
  apps:
  - name: wind-turbine
    metadata:
      helics:
        broker:
          hostname: helics-broker|IF0
        federate: OpenDSS
      ground-truth-module:
        elastic:
          endpoint: http://localhost:9200
          index-base-name: ot-sim
      templates:
        default:
          main-controller:
            turbine:
              type: E-126/4200
              helicsTopic: generator-$2_bus-2100.mw_setpoint
    hosts:
    # Complex regex to define nodes and link components
    - hostname: (.*-(.*))-main_controller
      metadata:
        type: main-controller
        template: default
        controllers:
          anemometer: $1-signal_converter
          yaw: $1-yaw_controller
          blades:
          - $1-blade_1
          - $1-blade_2
          - $1-blade_3
```

### After (Scale Plugin)

The new configuration is declarative and contained within a profile.

```yaml
spec:
  scenario:
    apps:
    - name: scale
      metadata:
        profiles:
        - name: my-wind-farm
          plugin: wind_turbine
          count: 5  # Create 5 complete turbines (30 containers)
          containers_per_node: 18 # Pack 3 turbines (18 containers) per VM

          # Network configuration for the main controllers
          container_template:
            external_network:
              name: ot
              network: 192.168.100.0/24
              gateway: 192.168.100.254

          # Configuration sections moved inside the profile
          helics:
            broker:
              hostname: helics-broker|IF0
            federate: OpenDSS
            # Dynamic topic generation using placeholders
            topic: "generator-{{turbine_id}}_bus-2100.mw_setpoint"

          ground-truth-module:
            elastic:
              endpoint: http://localhost:9200
              index-base-name: ot-sim
              labels:
                turbine: "{{turbine_name}}"

          templates:
            default:
              main-controller:
                turbine:
                  type: E-126/4200
```

## Configuration Mapping

| Old Config | New Config | Notes |
| :--- | :--- | :--- |
| `metadata.helics` | `profile.helics` | Structure remains mostly the same. |
| `metadata.ground-truth-module` | `profile.ground-truth-module` | Structure remains the same. Supports `{{turbine_name}}` variables. |
| `metadata.templates` | `profile.templates` | Structure remains the same. |
| `hosts` | **REMOVED** | Topology is now generated based on `count`. |
| N/A | `profile.count` | Number of turbines to simulate. |
| N/A | `profile.containers_per_node` | Density of containers per VM. |
| N/A | `profile.container_template` | Defines external network connectivity. |