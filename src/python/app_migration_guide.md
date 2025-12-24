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
