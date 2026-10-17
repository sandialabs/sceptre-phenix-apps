import json
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.pipe.pipe import Pipe, PipeMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_examples_are_valid_and_clean():
    examples = readme_components(README, "pipe")
    assert len(examples) == 5

    for cmp in examples:
        _, warnings = validate_metadata(PipeMetadata, cmp["metadata"], cmp["name"])
        assert warnings == []


def test_readme_json_example_is_valid_json():
    (cmp,) = [
        c for c in readme_components(README, "pipe") if c["name"] == "announce-run"
    ]
    assert json.loads(cmp["metadata"]["data"]) == {"event": "start", "duration": 300}


def test_blank_strings_are_unset_and_text_is_stripped():
    md = {"pipe": "p", "data": "  ", "via": "", "mode": " ", "log": True}
    config, warnings = validate_metadata(PipeMetadata, md, "p")

    assert warnings == []
    assert (config.data, config.via, config.mode, config.log) == (
        None,
        None,
        None,
        True,
    )

    md = {"pipe": "p", "data": " go ", "via": " cat "}
    config = parse_metadata(PipeMetadata, md, "p")
    assert (config.data, config.via) == ("go", "cat")


@pytest.mark.parametrize("data", [5, True, False, {"a": 1}, ["a"]])
def test_data_must_be_text(data):
    with pytest.raises(ValueError, match="data"):
        parse_metadata(PipeMetadata, {"pipe": "p", "data": data}, "p")


@pytest.mark.parametrize("field", ["via", "mode"])
@pytest.mark.parametrize("falsy", [False, 0, {}, []])
def test_falsy_values_are_type_errors(field, falsy):
    with pytest.raises(ValueError, match=field):
        parse_metadata(PipeMetadata, {"pipe": "p", field: falsy}, "p")


@pytest.mark.parametrize("log", ["maybe", {}, 5])
def test_log_must_be_a_bool(log):
    with pytest.raises(ValueError, match="log"):
        parse_metadata(PipeMetadata, {"pipe": "p", "log": log}, "p")


@pytest.mark.parametrize(
    ("md", "field"),
    [
        ({}, "pipe"),
        ({"pipe": "p'; shell id"}, "pipe"),
        ({"pipe": "p", "data": "it's"}, "data"),
        ({"pipe": "p", "data": "a\nclear pipe"}, "data"),
        ({"pipe": "p", "via": "cat\nshell id"}, "via"),
        ({"pipe": "p", "mode": "fifo"}, "mode"),
    ],
)
def test_bad_metadata_is_rejected(md, field):
    with pytest.raises(ValueError, match=field):
        parse_metadata(PipeMetadata, md, "p")


class FakeMinimega:
    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


def test_start_sets_up_then_writes():
    md = {"pipe": "p", "data": "go", "via": "cat", "mode": "all", "log": False}
    component = Pipe.__new__(Pipe)
    component.name = "pipe"
    component.config = parse_metadata(PipeMetadata, md, "p")
    component.mm = FakeMinimega()

    component.start()

    assert component.mm.calls == [
        ("pipe_via", "p", "cat"),
        ("pipe_mode", "p", "all"),
        ("pipe_log", "p", "false"),
        ("pipe", "p", "'go'"),
    ]


def test_cleanup_resets_the_pipe():
    component = Pipe.__new__(Pipe)
    component.name = "pipe"
    component.config = parse_metadata(PipeMetadata, {"pipe": "p"}, "p")
    component.mm = FakeMinimega()

    component.cleanup()

    assert component.mm.calls == [("clear_pipe", "p")]


def test_backslashes_are_doubled_for_the_minimega_lexer():
    # minimega expands \n, \\ and \' inside single quotes, so a JSON payload
    # (or a trailing backslash) would be corrupted if sent as written
    data = r'{"a":"x\ny"}\\'
    component = Pipe.__new__(Pipe)
    component.name = "pipe"
    component.config = parse_metadata(PipeMetadata, {"pipe": "p", "data": data}, "p")
    component.mm = FakeMinimega()

    component.start()

    ((_, _, sent),) = component.mm.calls
    assert sent == "'" + data.replace("\\", "\\\\") + "'"
    assert sent == r"""'{"a":"x\\ny"}\\\\'"""
