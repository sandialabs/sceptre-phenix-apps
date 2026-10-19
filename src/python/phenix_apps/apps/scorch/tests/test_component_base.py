import io
import json
import sys
from collections.abc import Callable

import pytest
from box import Box
from pydantic import BaseModel

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    Args,
    FilePath,
    FilterExpr,
    Hostname,
    Interface,
    MetadataBlock,
    Token,
    validate_metadata,
)


class Meta(BaseModel):
    count: int
    password: str = ""


class Component(ComponentBase):
    metadata_model = Meta

    def __init__(self):
        ComponentBase.__init__(self, "test")

    def configure(self):
        return f"count={self.config.count}"


@pytest.fixture
def run_component(monkeypatch, tmp_path):
    """Build a component the way phenix calls it, with the given metadata."""

    monkeypatch.setenv("PHENIX_FILES_DIR", str(tmp_path))

    def run(
        metadata: object,
        ctype: str | None = "test",
        cls: Callable[[], ComponentBase] = Component,
    ) -> ComponentBase:
        experiment = {
            "spec": {
                "experimentName": "exp",
                "baseDir": str(tmp_path),
                "scenario": {
                    "apps": [
                        {
                            "name": "scorch",
                            "metadata": {
                                "components": [
                                    {"name": "c", "type": ctype, "metadata": metadata}
                                ]
                            },
                        }
                    ]
                },
            }
        }
        monkeypatch.setattr(sys, "argv", ["x", "configure", "c", "0", "0", "0"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(experiment)))
        return cls()

    return run


def status(component: ComponentBase) -> dict:
    (path,) = component.base_dir.glob("configure-*.json")
    return json.loads(path.read_text())


def test_valid_metadata_reaches_the_stage(run_component):
    component = run_component({"count": 3})
    component.execute_stage()

    assert status(component)["return"] == "count=3"


def test_invalid_metadata_fails_the_stage_with_a_status_file(run_component):
    component = run_component({"count": "many"})

    with pytest.raises(RuntimeError, match="invalid metadata for component 'c'"):
        component.execute_stage()

    assert "count: Input should be a valid integer" in status(component)["return"]


class LegacyComponent(ComponentBase):
    """An out-of-tree component written before metadata_model existed."""

    def __init__(self):
        ComponentBase.__init__(self, "test")

    @property
    def config(self):
        return "own config"

    def configure(self):
        assert type(self.metadata) is Box
        return f"count={self.metadata.count}"


def test_component_without_a_model_reads_raw_metadata(run_component):
    # nothing is validated, and the base leaves its config property alone
    component = run_component({"count": "many", "typo": 1}, cls=LegacyComponent)
    component.execute_stage()

    assert status(component)["return"] == "count=many"
    assert component.config == "own config"


class Block(MetadataBlock):
    port: int = 1


class Outer(BaseModel):
    flag: bool = True
    blocks: list[Block] = []
    single: Block = Block()


def test_unknown_keys_warn_with_the_full_path_and_a_hint():
    md = {"blocks": [{}, {"prot": 2}], "single": {"other": 1}}
    _, warnings = validate_metadata(Outer, md, "c")

    assert warnings == [
        "blocks.1.prot: unknown key, ignored. Fix: remove it (did you mean 'port'?)",
        "single.other: unknown key, ignored. Fix: remove it (known: port)",
    ]


@pytest.mark.parametrize("value", [None, "maybe", "false", 2, [1]])
def test_values_are_typed_strictly(value):
    with pytest.raises(ValueError, match="flag"):
        validate_metadata(Outer, {"flag": value}, "c")


def test_numeric_strings_are_not_coerced():
    with pytest.raises(ValueError, match="port"):
        validate_metadata(Outer, {"single": {"port": "6"}}, "c")


@pytest.mark.parametrize("metadata", [False, [], 0, ""])
def test_only_missing_metadata_defaults_to_empty(metadata):
    with pytest.raises(ValueError, match="invalid metadata"):
        validate_metadata(Outer, metadata, "c")


def test_omitted_type_defaults_to_the_name(run_component):
    # phenix core treats a component with no type as type == name
    component = run_component({"count": 3}, ctype=None)
    component.name = component.type = "c"

    assert component.extract_metadata() == {"count": 3}


def test_a_traceback_does_not_leak_metadata_values(run_component, capsys):
    component = run_component({"count": "many", "password": "hunter2-secret"})

    with pytest.raises(RuntimeError):
        component.execute_stage()

    assert "hunter2-secret" not in capsys.readouterr().out
    assert "hunter2-secret" not in json.dumps(status(component))


class Fields(BaseModel):
    host: Hostname | None = None
    iface: Interface | None = None
    path: FilePath | None = None
    token: Token | None = None
    args: Args | None = None
    expr: FilterExpr | None = None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "rtu-1"),
        ("host", "AD"),
        ("iface", "eth0"),
        ("iface", "ens3.100"),
        ("iface", "br_mgmt"),
        ("path", "/tmp/out.json"),
        ("path", "C:/phenix/results.json"),
        ("path", "relative/dir/file-1.txt"),
        ("token", "--opt=value"),
        # minimega targets, a namespaced VLAN and an index name
        ("token", "vm[1-3]"),
        ("token", "a,b"),
        ("token", "ns//lan"),
        ("token", "rtds-clean"),
        ("args", ""),
        ("args", "-c 1000 -s 96"),
        ("args", "--omit 2 -b 10M --bind=10.0.0.1"),
        ("expr", ""),
        ("expr", "port 80"),
        ("expr", "(port 80 or port 443) and not host 1.2.3.4"),
        ("expr", "tcp[tcpflags] & tcp-syn != 0"),
    ],
)
def test_shared_field_types_accept(field, value):
    validate_metadata(Fields, {field: value}, "c")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "a"),
        ("host", "x" * 64),
        ("host", "-rtu"),
        ("host", "rtu_1"),
        ("host", "123"),
        ("host", "phenix"),
        ("iface", "eth 0"),
        ("iface", "a" * 16),
        ("iface", "eth0:1"),
        ("iface", "../eth0"),
        ("path", "/out.json&whoami"),
        ("path", "C:\\phenix\\out.json"),
        ("path", "/tmp/$(id)"),
        ("path", "/tmp/*.json"),
        ("path", "/tmp/a b"),
        ("token", "rtu#ignored"),
        ("token", "a\\tb"),
        ("token", "a;id"),
        ("token", "a|b"),
        ("token", "a&b"),
        ("token", "$(id)"),
        ("token", "`id`"),
        ("token", "a>b"),
        ("token", "two words"),
        ("args", "--omit 2; printf marker"),
        ("args", "a | b"),
        ("args", "$(id)"),
        ("args", "`id`"),
        ("args", "a && b"),
        ("args", "a > /etc/x"),
        ("args", "it's"),
        ("args", 'say "hi"'),
        ("args", "a\\nb"),
        ("args", "a\nb"),
        ("args", "a # b"),
        ("expr", "a; id"),
        ("expr", "$(id)"),
        ("expr", "`id`"),
        ("expr", "port 80 # x"),
        ("expr", "it's"),
        ("expr", 'a"b'),
        ("expr", "a\\b"),
        ("expr", "a\nb"),
    ],
)
def test_shared_field_types_reject(field, value):
    with pytest.raises(ValueError, match=field):
        validate_metadata(Fields, {field: value}, "c")


def test_stage_the_component_does_not_implement_skips_metadata(run_component):
    component = run_component({"count": "many"})
    component.stage = "cleanup"

    component.execute_stage()  # Component has no cleanup(), so no error

    assert component.config is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("baseline", "baseline"),
        ("run-1.a", "run-1.a"),
        (3, "3"),
        ("", "0"),
        # a name becomes part of a file name on the host
        ("../../etc/x", "0"),
        ("a/b", "0"),
        ("..", "0"),
        ("two words", "0"),
        ("a;b", "0"),
    ],
)
def test_run_name_is_safe_in_a_file_name(run_component, name, expected):
    component = run_component({"count": 1})
    component.experiment.spec.scenario.apps[0].metadata["runs"] = [{"name": name}]

    assert component.extract_run_name() == expected
