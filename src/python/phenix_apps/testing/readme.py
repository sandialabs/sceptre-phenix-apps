"""Helpers for tests that keep README examples honest.

A component README's examples are parsed by its tests, so an example that no
longer validates fails the build instead of misleading a reader.
"""

import re
from pathlib import Path
from typing import Any

import yaml


def readme_section(readme: Path, heading: str) -> str:
    """The text of the `## <heading>` section (up to the next `## `)."""

    text = readme.read_text()
    marker = f"\n## {heading}\n"
    if marker not in text:
        raise AssertionError(f"{readme} has no '## {heading}' section")
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def readme_yaml(readme: Path, heading: str = "Examples") -> list[Any]:
    """Every ```yaml block in a README section, parsed."""

    blocks = re.findall(
        r"```yaml\n(.*?)```", readme_section(readme, heading), re.DOTALL
    )
    return [yaml.safe_load(block) for block in blocks]


def readme_components(
    readme: Path, component_type: str, heading: str = "Examples"
) -> list[dict]:
    """Every SCORCH component entry of `component_type` in a README section."""

    return [
        component
        for doc in readme_yaml(readme, heading)
        for component in doc.get("components", [])
        if component.get("type") == component_type
    ]
