"""Helpers for the capture commands of minimega 3.4.0 and later.

The SCORCH components use them to choose between the new per-capture options
and the older namespace-wide settings.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from phenix_apps.common import utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger

# A pre-release such as 3.4.0-rc1 counts, so release candidates can be tested.
MIN_CAPTURE_VERSION: Final = (3, 4, 0)

# Open vSwitch ignores a mirror added to a bridge that already has this many.
OVS_MIRROR_LIMIT: Final = 32

MIN_SNAPLEN: Final = 14
MAX_SNAPLEN: Final = 65535

# States after which a capture no longer writes packets.
FAILED_STATES: Final = frozenset({"failed", "orphaned"})
WARN_STATES: Final = frozenset({"full", "stalled"})

_VERSION: Final = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

# One item of a comma-separated option value: no space, quote, comma or "#".
_NAME: Final = re.compile(r"[\w.:+-]+")


@dataclass(frozen=True)
class CaptureSupport:
    """Whether the minimega nodes have the 3.4.0 capture commands."""

    available: bool
    version: str = ""
    reason: str = ""

    def require(self, what: str) -> None:
        """Raise unless the capture commands exist; `what` names the feature."""

        if not self.available:
            raise RuntimeError(f"{what} {self.reason}")


def _minimum() -> str:
    return ".".join(str(n) for n in MIN_CAPTURE_VERSION)


def parse_version(answer: str) -> tuple[int, int, int] | None:
    """The version in a `minimega <version> <revision> <date>` answer."""

    fields = answer.split()
    if len(fields) < 2:
        return None

    match = _VERSION.match(fields[1])
    if not match:
        return None

    major, minor, patch = (int(n) for n in match.groups())
    return major, minor, patch


def capture_support(mm: Any) -> CaptureSupport:
    """Ask minimega for its version once and compare it with 3.4.0.

    The answer of every node counts, so the oldest node decides. A version that
    cannot be read gives an unsupported result, so the old commands are used.
    """

    answers = [
        resp.get("Response", "")
        for resp in mm.version() or []
        if isinstance(resp, dict) and not resp.get("Error")
    ]
    versions = [parse_version(str(a)) for a in answers]

    if not versions or None in versions:
        shown = "; ".join(str(a).strip() for a in answers) or "no answer"
        return CaptureSupport(
            False,
            reason=(
                f"requires minimega {_minimum()} or later; cannot read the "
                f"minimega version ({shown})"
            ),
        )

    oldest = min(v for v in versions if v is not None)
    shown = ".".join(str(n) for n in oldest)

    if oldest < MIN_CAPTURE_VERSION:
        return CaptureSupport(
            False,
            version=shown,
            reason=(
                f"requires minimega {_minimum()} or later; the oldest node runs {shown}"
            ),
        )

    return CaptureSupport(True, version=shown)


def namespace_vlans(
    explicit: Iterable[str] | None, experiment_vlans: Iterable[str] | None
) -> list[str]:
    """The VLANs of a namespace capture: the ones given, else every VLAN of the
    experiment except MGMT, whose traffic is not experiment traffic."""

    if explicit:
        return list(explicit)

    vlans = sorted(a for a in experiment_vlans or () if a.lower() != "mgmt")
    if not vlans:
        raise ValueError(
            "the experiment has no VLAN besides MGMT to capture; set vlans"
        )

    return vlans


def check_snaplen(snaplen: int | None) -> int | None:
    """The snaplen minimega accepts per capture, or None for its default."""

    if not snaplen:
        return None

    if not MIN_SNAPLEN <= snaplen <= MAX_SNAPLEN:
        raise ValueError(
            f"snaplen {snaplen} is not from {MIN_SNAPLEN} to {MAX_SNAPLEN}, "
            "the range minimega accepts for one capture"
        )

    return snaplen


def _names(kind: str, values: Iterable[str]) -> str:
    out = []
    for value in values:
        if not _NAME.fullmatch(value):
            raise AppError(f"invalid {kind} {value!r} in a minimega capture option")
        out.append(value)

    return ",".join(out)


def capture_options(
    *,
    filter: str | None = None,  # noqa: A002
    snaplen: int | None = None,
    format: str | None = None,  # noqa: A002
    vlans: Iterable[str] = (),
    vms: Iterable[str] = (),
    bridges: Iterable[str] = (),
) -> str | None:
    """The `[option]...` text of a minimega 3.4.0 capture command, or None.

    Every value is checked here, so nothing unsafe reaches the command line.
    """

    options: list[str] = []

    if format:
        options.append(f"format={_names('format', [format])}")
    if vlans:
        options.append(f"vlans={_names('vlan', vlans)}")
    if bridges:
        options.append(f"bridges={_names('bridge', bridges)}")
    if vms:
        options.append(f"vms={_names('vm', vms)}")
    if filter:
        options.append(f"filter='{utils._validate_mm_filter(filter)}'")
    if (size := check_snaplen(snaplen)) is not None:
        options.append(f"snaplen={size}")

    return " ".join(options) or None


def rows(resps: Any) -> list[dict[str, str]]:
    """Rows of minimega table responses, keyed by their own header.

    Never index a column by position: minimega adds columns between releases.
    """

    out: list[dict[str, str]] = []

    for resp in resps or []:
        if not isinstance(resp, dict):
            continue

        header = resp.get("Header") or []
        out.extend(
            dict(zip(header, row, strict=False)) for row in resp.get("Tabular") or []
        )

    return out


def path_of(row: dict[str, str]) -> Path | None:
    """The capture file of a listing row."""

    return Path(row["path"]) if row.get("path") else None


def is_under(row: dict[str, str], folder: Path) -> bool:
    """True when the row's capture file is in `folder` or below it."""

    path = path_of(row)
    return path is not None and path.is_relative_to(folder)


def counter(value: str | None) -> int | str | None:
    """A counter column as an integer, or as it is when it is not one."""

    if value is None or value == "":
        return None

    try:
        return int(value)
    except ValueError:
        return value


def summarize(row: dict[str, str]) -> dict[str, Any]:
    """The state and counters of a listing row, for a status file."""

    summary: dict[str, Any] = {}

    for key in ("state", "packets", "kdrops"):
        if (value := counter(row.get(key))) is not None:
            summary[f"minimega_{key}"] = value

    return summary


def check_final(rows_: Iterable[dict[str, str]]) -> None:
    """Raise with minimega's error for each capture that failed.

    A capture that stopped because it was full or stalled only logs a warning.
    """

    failed: list[str] = []

    for row in rows_:
        state = row.get("state", "")
        where = row.get("path") or f"id {row.get('id', '?')}"

        if state in FAILED_STATES:
            failed.append(f"{where}: {state}: {row.get('error') or 'no error given'}")
        elif state in WARN_STATES:
            logger.warning(
                f"minimega capture {where} is {state}; its file may end early"
            )

    if failed:
        raise RuntimeError("minimega capture failed: " + "; ".join(failed))


def count_mirrors(output: str) -> int:
    """The number of rows in `ovs-vsctl get Bridge <br> mirrors` output."""

    text = output.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError(f"cannot read the Open vSwitch mirror list {output!r}")

    return len([m for m in text[1:-1].split(",") if m.strip()])
