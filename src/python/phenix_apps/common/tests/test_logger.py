import json
from datetime import UTC, datetime

from phenix_apps.common import logger as logger_module


class _DummyLevel:
    def __init__(self, name: str):
        self.name = name


class _DummyFile:
    def __init__(self, name: str):
        self.name = name


class _DummyMessage:
    def __init__(self, text: str):
        self.record = {
            "level": _DummyLevel("INFO"),
            "message": text,
            "time": datetime(2026, 4, 17, tzinfo=UTC),
            "file": _DummyFile("cc.py"),
            "line": 113,
            "exception": None,
            "extra": {"component": "cc"},
        }


class _CaptureStream:
    def __init__(self):
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, text: str):
        self.writes.append(text)

    def flush(self):
        self.flush_count += 1


def test_format_phenix_json_log_keeps_small_messages_single_line():
    formatted = logger_module._format_phenix_json_log(_DummyMessage("hello world"))

    lines = formatted.splitlines()

    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["msg"] == "hello world"
    assert entry["component"] == "cc"
    assert "part" not in entry


def test_format_phenix_json_log_splits_multiline_messages():
    formatted = logger_module._format_phenix_json_log(
        _DummyMessage("line one\nline two")
    )

    entries = [json.loads(line) for line in formatted.splitlines()]

    assert [entry["msg"] for entry in entries] == ["line one", "line two"]
    assert all(entry["parts"] == 2 for entry in entries)


def test_format_phenix_json_log_splits_long_lines_into_chunks():
    long_line = "x" * (logger_module.PHENIX_JSON_LOG_CHUNK_SIZE + 25)
    formatted = logger_module._format_phenix_json_log(_DummyMessage(long_line))

    entries = [json.loads(line) for line in formatted.splitlines()]

    assert len(entries) == 2
    assert "".join(entry["msg"] for entry in entries) == long_line
    assert all(
        len(entry["msg"]) <= logger_module.PHENIX_JSON_LOG_CHUNK_SIZE
        for entry in entries
    )


def test_phenix_stderr_sink_writes_chunked_frames_individually(monkeypatch):
    capture = _CaptureStream()
    long_line = "x" * (logger_module.PHENIX_JSON_LOG_CHUNK_SIZE + 25)

    monkeypatch.setattr(logger_module.sys, "stderr", capture)

    logger_module.phenix_stderr_sink(_DummyMessage(f"line one\n{long_line}"))

    assert len(capture.writes) == 3
    assert capture.flush_count == 3

    entries = [json.loads(line) for line in capture.writes]

    assert entries[0]["msg"] == "line one"
    assert "".join(entry["msg"] for entry in entries[1:]) == long_line
    assert [entry["part"] for entry in entries] == [1, 2, 3]
    assert all(entry["parts"] == 3 for entry in entries)
