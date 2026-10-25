import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from mako.lookup import TemplateLookup

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.caldera.caldera import (
    PHENIX_PLANNER_ID,
    Caldera,
    CalderaMetadata,
)
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "caldera")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(CalderaMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    md = {"server": "mallory", "adversary": "superbad", "facts": "recon"}
    assert parse_metadata(CalderaMetadata, md, "c").planner == PHENIX_PLANNER_ID


@pytest.mark.parametrize(
    "ref",
    [
        "Ransom Sim",
        "Ops (v2) & more",
        PHENIX_PLANNER_ID,
        "a.b-c_1",
        'x"y',
        "a\\b",
        "${x}",
    ],
)
def test_names_and_uuids_are_accepted(ref):
    md = {"server": "mallory", "adversary": ref, "facts": ref, "planner": ref}
    assert parse_metadata(CalderaMetadata, md, "c").adversary == ref


GOOD = {"server": "mallory", "adversary": "superbad", "facts": "recon"}


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({k: v for k, v in GOOD.items() if k != "server"}, "server: Field required"),
        ({k: v for k, v in GOOD.items() if k != "adversary"}, "adversary: Field req"),
        ({k: v for k, v in GOOD.items() if k != "facts"}, "facts: Field required"),
        ({**GOOD, "server": "a"}, "server"),
        ({**GOOD, "server": "m;reboot"}, "server"),
        ({**GOOD, "adversary": ""}, "adversary"),
        ({**GOOD, "adversary": "x'y"}, "adversary"),
        ({**GOOD, "facts": "a\tb"}, "facts"),
        ({**GOOD, "planner": ""}, "planner"),
        ({**GOOD, "planner": "a\nb"}, "planner"),
        ({**GOOD, "planner": 5}, "planner"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(CalderaMetadata, md, "c")


def test_unknown_top_level_key_is_accepted_without_warning():
    _, warnings = validate_metadata(CalderaMetadata, {**GOOD, "bogus": 1}, "c")
    assert warnings == []


TEMPLATES = Path(__file__).parents[1] / "templates"


def test_operation_body_is_json_safe():
    name = 'bad"\\ ${x} (v2)'
    op = {"name": name, "adversary": "a", "facts": "f", "planner": "p"}
    out = (
        TemplateLookup([str(TEMPLATES)])
        .get_template("new_operation.mako")
        .render(op=op)
    )
    body = out[out.index("-d '") + 4 : out.rindex("'")]
    assert json.loads(body)["name"] == name


def make_app(**cfg):
    app = Caldera.__new__(Caldera)
    app.config = CalderaMetadata(**{**GOOD, **cfg})
    return app


def test_resolve_uuid_skips_lookup():
    a = make_app()
    with mock.patch.object(Caldera, "_api") as api:
        assert (
            a._resolve(None, "planners", "planner", PHENIX_PLANNER_ID)
            == PHENIX_PLANNER_ID
        )
    api.assert_not_called()


@pytest.mark.parametrize(
    ("model", "item", "want"),
    [
        ("adversaries", {"name": "n", "adversary_id": "A1"}, "A1"),
        ("sources", {"name": "n", "id": "S1"}, "S1"),
    ],
)
def test_resolve_looks_up_name(model, item, want):
    app = make_app()
    with mock.patch.object(
        Caldera, "_api", return_value=[{"name": "x", "id": "no"}, item]
    ) as api:
        assert app._resolve("mm", model, "thing", "n") == want
    api.assert_called_once_with("mm", "api_call.mako", model, model=model)


def test_resolve_unknown_name_raises():
    app = make_app()
    with mock.patch.object(Caldera, "_api", return_value=[]):
        with pytest.raises(ValueError, match="unable to find 'bogus' planner"):
            app._resolve("mm", "planners", "planner", "bogus")


def test_run_wires_lookups_into_the_operation():
    app = make_app(adversary="adv", planner=PHENIX_PLANNER_ID)
    app.name = "op1"
    app.base_dir = (
        Path(sys.modules["tempfile"].mkdtemp()) if "tempfile" in sys.modules else None
    )
    calls = []

    def fake_api(mm, template, what, **kw):
        calls.append((template, kw))
        return {
            "api_call.mako": [
                {"name": "adv", "adversary_id": "A1"},
                {"name": "recon", "id": "F1"},
            ],
            "new_operation.mako": {"id": "OP"},
            "get_operation.mako": {"state": "finished"},
        }.get(template, {})

    with (
        mock.patch.object(Caldera, "_api", side_effect=fake_api),
        mock.patch.object(Caldera, "mm_init"),
        mock.patch("phenix_apps.apps.scorch.caldera.caldera.time.sleep"),
        mock.patch("builtins.open", mock.mock_open()),
        mock.patch("phenix_apps.apps.scorch.caldera.caldera.json.dump"),
    ):
        app._Caldera__run("start")

    op = next(kw["op"] for t, kw in calls if t == "new_operation.mako")
    # _run adds the new operation id to the same dict after the call
    assert op == {
        "name": "op1",
        "adversary": "A1",
        "facts": "F1",
        "planner": PHENIX_PLANNER_ID,
        "id": "OP",
    }
