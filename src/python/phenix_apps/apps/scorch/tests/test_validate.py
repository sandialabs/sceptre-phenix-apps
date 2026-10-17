import pytest
from pydantic import BaseModel

from phenix_apps.apps.scorch import validate
from phenix_apps.apps.scorch.app import MetadataBlock


class Settings(MetadataBlock):
    count: int


class Model(BaseModel):
    settings: Settings


@pytest.fixture
def models(monkeypatch):
    known = {"thing": Model}
    monkeypatch.setattr(validate, "metadata_model", known.get)


def test_scenario_and_bare_blocks_are_both_read():
    bare = {"components": [{"name": "a"}]}
    v2 = {"spec": {"apps": [{"name": "scorch", "metadata": bare}]}}
    v1 = {"spec": {"apps": {"experiment": [{"name": "scorch", "metadata": bare}]}}}

    assert validate.scorch_metadata(bare) is bare
    assert validate.scorch_metadata(v2) is bare
    assert validate.scorch_metadata(v1) is bare
    for empty in [{"spec": {"apps": []}}, {"spec": {"apps": None}}, {"spec": None}]:
        assert validate.scorch_metadata(empty) is None


@pytest.mark.parametrize(
    "doc",
    [
        {"spec": []},
        {"spec": {"apps": "scorch"}},
        {"spec": {"apps": [None]}},
        {"spec": {"apps": [{"name": "scorch", "metadata": []}]}},
    ],
)
def test_malformed_scenario_is_an_error(doc):
    with pytest.raises(ValueError, match="not a"):
        validate.scorch_metadata(doc)


def test_replace_keys_come_from_nested_loops():
    runs = [{"replace": {"@A@": [1]}, "loop": {"replace": {"@B@": [2]}}}, None]

    assert validate.replace_keys(runs) == {"@A@", "@B@"}


@pytest.mark.usefixtures("models")
def test_check_reports_each_component(tmp_path, capsys):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
components:
  - {name: good, type: thing, metadata: {settings: {count: 1}}}
  - {name: typo, type: thing, metadata: {settings: {count: 1, cout: 2}}}
  - {name: bad, type: thing, metadata: {settings: {count: many}}}
  - {name: other, type: unknown, metadata: {}}
"""
    )

    assert validate.check(path) is False
    out = capsys.readouterr().out.splitlines()

    assert out[0] == f"ok       {path}: good (thing)"
    assert out[1].startswith(
        f"warning  {path}: typo (thing): settings.cout: unknown key"
    )
    assert out[2] == f"ok       {path}: typo (thing)"
    assert out[3].startswith(f"invalid  {path}: bad (thing): invalid metadata")
    assert out[-1].startswith(f"skipped  {path}: other (unknown)")


@pytest.mark.usefixtures("models")
def test_omitted_or_empty_type_defaults_to_the_name(tmp_path, capsys):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
components:
  - {name: thing, metadata: {settings: {count: many}}}
  - {name: thing, type: "", metadata: {settings: {count: many}}}
"""
    )

    assert validate.check(path) is False
    out = capsys.readouterr().out
    assert out.count(f"invalid  {path}: thing (thing): invalid metadata") == 2


@pytest.mark.usefixtures("models")
def test_malformed_components_are_invalid_and_checking_continues(tmp_path, capsys):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
components: [null, {name: good, type: thing, metadata: {settings: {count: 1}}}]
---
components: {name: bad}
---
spec: {apps: [null]}
"""
    )

    assert validate.check(path) is False
    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"invalid  {path}: components.0 is not a mapping",
        f"ok       {path}: good (thing)",
        f"invalid  {path}: components is not a list",
        f"invalid  {path}: spec.apps.0 is not a mapping",
    ]


def test_a_component_that_cannot_load_is_invalid(tmp_path, capsys, monkeypatch):
    def broken(_):
        raise ImportError("no module named paramiko")

    monkeypatch.setattr(validate, "metadata_model", broken)
    path = tmp_path / "scenario.yaml"
    path.write_text("components: [{name: a, type: ssh, metadata: {}}]")

    assert validate.check(path) is False
    assert capsys.readouterr().out.startswith(f"invalid  {path}: a (ssh): cannot")


@pytest.mark.usefixtures("models")
def test_metadata_using_replace_keys_is_deferred(tmp_path, capsys):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        """
runs:
  - loop: {replace: {"@COUNT@": [1, 2]}}
components:
  - {name: a, type: thing, metadata: {settings: {count: "@COUNT@"}}}
"""
    )

    assert validate.check(path) is True
    assert capsys.readouterr().out.startswith(
        f"deferred {path}: a (thing): uses replace key(s) @COUNT@"
    )


def test_unreadable_file_is_invalid(tmp_path, capsys):
    assert validate.check(tmp_path / "missing.yaml") is False
    assert capsys.readouterr().out.startswith("invalid  ")
