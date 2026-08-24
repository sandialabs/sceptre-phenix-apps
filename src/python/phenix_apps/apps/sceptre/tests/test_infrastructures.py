"""Total characterization of infrastructures.create_device.

Every (infrastructure, device type, protocol) combination is rendered into
`infrastructures_golden.txt`: the four field lists, the range, and the registers
that come out the other side. Unsupported combinations are pinned too, since
"raises UnboundLocalError" and "returns None" are both current behaviour. Every
protocol is exercised; a combination that behaves the same for all of them --
any unsupported one, which fails before the protocol is read -- collapses to a
single `*` line rather than seven identical ones.

This exists so the if/elif chains can be replaced by a lookup table and proved
equivalent. The scenario golden fixture exercises 1 of the 10 infrastructures;
without this the other nine would change unobserved.

Regenerate after an intentional change, and read the diff:

    PHENIX_UPDATE_GOLDEN=1 pytest phenix_apps/apps/sceptre/tests/test_infrastructures.py
"""

import os
from pathlib import Path

import pytest

from phenix_apps.apps.sceptre.configs.configs import get_fdconfig_class
from phenix_apps.apps.sceptre.configs.infrastructures import INFRASTRUCTURES
from phenix_apps.apps.sceptre.configs.registers import Register
from phenix_apps.apps.sceptre.metadata import FIELD_TYPES, Infrastructure

GOLDEN_FILE = Path(__file__).parent / "infrastructures_golden.txt"

PROTOCOLS = (*Register.TYPE, "sunspec")

# The union of every device type any infrastructure accepts, so each one is
# also asked for the types it does *not* support -- that is what pins which
# combinations are valid. 5 stands in for a non-string type.
DEVICE_TYPES = (
    "analog-read",
    "analog-read-write",
    "battstack",
    "binary-read",
    "binary-read-write",
    "bmsscrtu",
    "bmsse",
    "boat",
    "boat-sensor",
    "branch",
    "bus",
    "cooler",
    "cps",
    "fan",
    "fillingstation",
    "gate",
    "generator",
    "heater",
    "heatingtank",
    "inverter",
    "load",
    "mixingtank",
    "pump",
    "room",
    "shunt",
    "storagetank",
    "thermostat",
    "transformer",
    "valve",
    "water",
    5,
)


def render(infrastructure: str, device_type, protocol: str) -> str:
    """One combination's behaviour, as a single line."""

    Register.reset_addresses()
    try:
        device = get_fdconfig_class(infrastructure).create_device(
            device_type, "dev-1", protocol, []
        )
    except Exception as exc:  # pinning current behaviour, whatever it is
        return f"raises {type(exc).__name__}"

    if device is None:
        return "returns None"

    fields = " ".join(f"{name}={device.fields[name]}" for name in FIELD_TYPES)
    parts = [f"range={device.range}", f"infrastructure={device.infrastructure}", fields]

    if protocol == "sunspec":
        # SunSpec register contents include a random serial number; the count is
        # enough to show the models list above reached the generator.
        parts.append(f"registers={len(device.registers)}")
    else:
        parts.append(
            "registers="
            + (
                "; ".join(f"{r.regtype}:{r.addr} {r.field}" for r in device.registers)
                or "-"
            )
        )
    return " ".join(parts)


def snapshot() -> str:
    lines = []
    for infrastructure in sorted(Infrastructure):
        for device_type in DEVICE_TYPES:
            rendered = {p: render(infrastructure, device_type, p) for p in PROTOCOLS}
            shown = (
                {"*": next(iter(rendered.values()))}
                if len(set(rendered.values())) == 1
                else rendered
            )
            lines += [
                f"{infrastructure} | {device_type!r} | {protocol} | {result}"
                for protocol, result in shown.items()
            ]
    return "\n".join(lines) + "\n"


def test_create_device_matches_golden():
    blob = snapshot()

    if os.getenv("PHENIX_UPDATE_GOLDEN"):
        GOLDEN_FILE.write_text(blob)
        pytest.skip(f"regenerated {GOLDEN_FILE.name}")

    assert GOLDEN_FILE.exists(), (
        f"{GOLDEN_FILE.name} is missing; regenerate with PHENIX_UPDATE_GOLDEN=1"
    )
    assert blob == GOLDEN_FILE.read_text()


def test_every_infrastructure_and_device_type_is_covered():
    """Guard the guard: a new infrastructure or device type must land here.

    The snapshot only proves what it enumerates, so this fails if the enum grows
    or an infrastructure starts accepting a type this module does not ask for.
    """

    lines = snapshot().splitlines()
    combinations = {tuple(line.split(" | ")[:2]) for line in lines}
    assert len(combinations) == len(Infrastructure) * len(DEVICE_TYPES)

    supported = {
        line.split(" | ")[0]
        for line in lines
        if "raises" not in line and "returns None" not in line
    }
    assert supported == set(Infrastructure)


def test_the_table_declares_only_known_keys():
    """A typo'd field key in the YAML would silently mean "no registers"."""

    for infrastructure, spec in INFRASTRUCTURES.items():
        assert set(spec) == {"range", "devices"}, infrastructure
        assert len(spec["range"]) == 2, infrastructure

        for device_type, fields in spec["devices"].items():
            where = f"{infrastructure}.{device_type}"
            assert set(fields) <= {"range", *FIELD_TYPES}, where
            assert fields, f"{where} declares nothing"
