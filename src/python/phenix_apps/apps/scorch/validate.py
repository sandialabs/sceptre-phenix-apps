"""Check SCORCH component metadata before running an experiment.

    phenix-scorch-validate scenario.yaml [more.yaml ...]

Each file is a phenix Scenario whose `scorch` app holds the components, or a
bare SCORCH app metadata block (`components: [...]`). Every component whose
type has a metadata model is validated the way its stages will validate it,
except one whose metadata uses a run/loop `replace` key, which is deferred.
Exits non-zero if any component is invalid or cannot be loaded.
"""

import argparse
import importlib
import inspect
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from phenix_apps.apps.scorch.app import ComponentBase, validate_metadata


def metadata_model(component_type: str) -> type[BaseModel] | None:
    """The metadata model for a component type, found via its console script."""

    scripts = entry_points(group="console_scripts")
    matches = [
        s for s in scripts if s.name == f"phenix-scorch-component-{component_type}"
    ]
    if not matches:
        return None
    module = importlib.import_module(matches[0].module)  # errors reach check()
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if issubclass(cls, ComponentBase) and cls.metadata_model is not None:
            return cls.metadata_model
    return None


def scorch_metadata(doc: Any) -> dict | None:
    """The SCORCH app metadata in a Scenario (v1 or v2), or a bare SCORCH
    metadata block. None if the document has none; ValueError if it is
    malformed."""

    if not isinstance(doc, dict):
        return None
    if "components" in doc:
        return doc
    spec = doc.get("spec")
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError("spec is not a mapping")
    apps = spec.get("apps") or []
    if isinstance(apps, dict):  # v1 Scenario: spec.apps.experiment
        apps = apps.get("experiment") or []
    if not isinstance(apps, list):
        raise ValueError("spec.apps is not a list")
    for index, app in enumerate(apps):
        if not isinstance(app, dict):
            raise ValueError(f"spec.apps.{index} is not a mapping")
        if app.get("name") == "scorch":
            metadata = app.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("scorch app metadata is not a mapping")
            return metadata
    return None


def replace_keys(loops: Any) -> set[str]:
    """The run/loop `replace` keys, which phenix substitutes into component
    metadata before each loop, so they cannot be checked here."""

    keys: set[str] = set()
    for loop in loops if isinstance(loops, list) else []:
        if isinstance(loop, dict):
            replace = loop.get("replace")
            keys |= set(replace) if isinstance(replace, dict) else set()
            keys |= replace_keys([loop.get("loop")])
    return keys


def _uses(value: Any, keys: set[str]) -> set[str]:
    if isinstance(value, str):
        return {key for key in keys if key in value}
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return set().union(*(_uses(item, keys) for item in value))
    return set()


def check(path: Path) -> bool:
    """Print a line per component in `path`; True if none is invalid."""

    try:
        docs = list(yaml.safe_load_all(path.read_text()))
    except (OSError, yaml.YAMLError) as ex:
        print(f"invalid  {path}: {ex}")
        return False

    valid = True
    for doc in docs:
        try:
            block = scorch_metadata(doc) or {}
        except ValueError as ex:
            print(f"invalid  {path}: {ex}")
            valid = False
            continue
        components = block.get("components") or []
        if not isinstance(components, list):
            print(f"invalid  {path}: components is not a list")
            valid = False
            continue
        keys = replace_keys(block.get("runs"))
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                print(f"invalid  {path}: components.{index} is not a mapping")
                valid = False
                continue
            name = component.get("name") or "?"
            # phenix core defaults an omitted or empty type to the name
            ctype = component.get("type") or name
            label = f"{path}: {name} ({ctype})"
            try:
                model = metadata_model(ctype)
            except ImportError as ex:
                print(f"invalid  {label}: cannot load the component: {ex}")
                valid = False
                continue
            if model is None:
                print(f"skipped  {label}: no metadata model for this type yet")
                continue
            used = _uses(component.get("metadata"), keys)
            if used:
                print(
                    f"deferred {label}: uses replace key(s) "
                    f"{', '.join(sorted(used))}; checked when the loop runs"
                )
                continue
            try:
                _, warnings = validate_metadata(model, component.get("metadata"), name)
            except ValueError as ex:
                valid = False
                print(f"invalid  {label}: {ex}")
                continue
            for warning in warnings:
                print(f"warning  {label}: {warning}")
            print(f"ok       {label}")
    return valid


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="phenix-scorch-validate",
        description="Check SCORCH component metadata before running an experiment.",
    )
    parser.add_argument("files", nargs="+", type=Path, help="Scenario or SCORCH YAML")
    args = parser.parse_args()

    results = [check(path) for path in args.files]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
