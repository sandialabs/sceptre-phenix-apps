"""Characterization test for the sceptre app.

Runs the configure and pre-start stages against a fixed experiment input and
asserts that both the emitted experiment JSON and every generated file are
unchanged. This exists to make refactoring app.py safe: it does not assert that
the output is *correct*, only that it has not moved.

Regenerate after an intentional behaviour change:

    PHENIX_UPDATE_GOLDEN=1 pytest phenix_apps/apps/sceptre/tests/test_sceptre_golden.py

When a file hash differs and you need to see *what* changed, dump both trees and
diff them directly:

    phenix-app-sceptre configure --dry-run < tests/test_sceptre_input.yaml
"""

import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.sceptre.app import Sceptre

HERE = Path(__file__).parent
INPUT_FILE = HERE / "test_sceptre_input.yaml"
GOLDEN_FILE = HERE / "sceptre_golden.json"


def _run_stage(monkeypatch, raw_input: str, stage: str, base_dir: Path) -> str:
    """Run one sceptre stage against raw_input, returning the experiment JSON."""
    experiment = Box.from_yaml(raw_input)
    experiment.spec.baseDir = str(base_dir)

    monkeypatch.setattr("sys.stdin", io.StringIO(experiment.to_json()))
    app = Sceptre("sceptre", stage)

    # Call the stage method directly rather than execute_stage(), which swallows
    # the exception and calls sys.exit(1) -- useless for a failing test.
    {"configure": app.configure, "pre-start": app.pre_start}[stage]()

    return app.experiment.to_json(indent=2)


def _manifest(root: Path) -> dict[str, str]:
    """Map every file under root to a sha256 of its contents."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _capture(monkeypatch, base_dir: Path) -> dict:
    """Run both stages in sequence and snapshot what each produced.

    pre-start is fed the configure stage's output, the way phenix chains them.
    """

    configure_json = _run_stage(
        monkeypatch, INPUT_FILE.read_text(), "configure", base_dir
    )
    configure_files = _manifest(base_dir)

    pre_start_json = _run_stage(monkeypatch, configure_json, "pre-start", base_dir)
    pre_start_files = _manifest(base_dir)

    return {
        "configure": {
            "experiment": json.loads(configure_json),
            "files": configure_files,
        },
        "pre_start": {
            "experiment": json.loads(pre_start_json),
            "files": pre_start_files,
        },
    }


def test_stages_match_golden(monkeypatch, tmp_path):
    base_dir = tmp_path / "exp"
    actual = _capture(monkeypatch, base_dir)

    # baseDir is rewritten to tmp_path, so every absolute path in the output has
    # to be normalised before comparison.
    blob = json.dumps(actual, indent=2, sort_keys=True).replace(
        str(base_dir), "{BASE_DIR}"
    )

    if os.getenv("PHENIX_UPDATE_GOLDEN"):
        GOLDEN_FILE.write_text(blob + "\n")
        pytest.skip(f"regenerated {GOLDEN_FILE.name}")

    assert GOLDEN_FILE.exists(), (
        f"{GOLDEN_FILE.name} is missing; regenerate with PHENIX_UPDATE_GOLDEN=1"
    )
    assert json.loads(blob) == json.loads(GOLDEN_FILE.read_text())


def test_output_is_deterministic(monkeypatch, tmp_path):
    """Guard the golden test itself: two runs must agree.

    If a mako template ever starts embedding a timestamp, this fails first and
    explains why the golden comparison went flaky.
    """
    first = _capture(monkeypatch, tmp_path / "a")
    second = _capture(monkeypatch, tmp_path / "b")

    normalise = lambda blob, d: json.loads(  # noqa: E731
        json.dumps(blob, sort_keys=True).replace(str(d), "{BASE_DIR}")
    )
    assert normalise(first, tmp_path / "a") == normalise(second, tmp_path / "b")
