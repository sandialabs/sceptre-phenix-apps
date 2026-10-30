import pytest

from phenix_apps.apps.scorch.cc.cc import _check_windows_result, _windows_script
from phenix_apps.common.logger import logger


@pytest.fixture
def warnings():
    seen: list[str] = []
    sink = logger.add(
        lambda m: seen.append(m.record["message"]),
        filter=lambda r: r["level"].name == "WARNING",
    )
    yield seen
    logger.remove(sink)


def test_script_exits_with_the_last_native_exit_code():
    script = _windows_script("robocopy C:\\a C:\\b")

    lines = script.splitlines()
    assert lines[0] == "robocopy C:\\a C:\\b"
    assert lines[-1] == "exit ([int]$LASTEXITCODE)"


def test_script_checks_the_command_status_first():
    # a failed cmdlet sets only $?, which the next statement overwrites
    lines = _windows_script("Get-Item C:\\nope").splitlines()

    assert lines[1].startswith("if (-not $?)")


@pytest.mark.parametrize("first", ["using namespace System.IO", "param($x = 1)"])
def test_script_leaves_the_command_first(first):
    # `using` and `param()` must be the first statements in a script
    assert _windows_script(f"{first}\nWrite-Output hi").startswith(first + "\n")


def result(code, stderr):
    return {"exitcode": code, "stderr": stderr, "stdout": ""}


def test_non_zero_exit_with_stderr_fails():
    with pytest.raises(RuntimeError, match="failed on Windows"):
        _check_windows_result("x", "win", result(3, "boom"))


@pytest.mark.parametrize("stderr", [None, ""])
def test_non_zero_exit_without_stderr_only_warns(warnings, stderr):
    _check_windows_result("x", "win", result(3, stderr))

    assert len(warnings) == 1
    assert "exited 3 without writing to STDERR" in warnings[0]


def test_stderr_with_exit_zero_passes_with_a_warning(warnings):
    _check_windows_result("x", "win", result(0, "progress noise"))

    assert len(warnings) == 1
    assert "no longer fail on STDERR alone" in warnings[0]


@pytest.mark.parametrize("stderr", [None, ""])
def test_clean_success_is_quiet(warnings, stderr):
    _check_windows_result("x", "win", result(0, stderr))

    assert warnings == []


@pytest.mark.parametrize(
    ("code", "stderr"), [(0, None), (0, ""), (3, None), (3, ""), (-1, None)]
)
def test_nothing_that_passed_before_starts_failing(code, stderr):
    # the old rule passed every Windows command that wrote no STDERR
    _check_windows_result("x", "win", result(code, stderr))
