import time
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.opcexport.opcexport import OPCExport, OpcexportMetadata
from phenix_apps.common import utils
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "opcexport")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(OpcexportMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    config = parse_metadata(OpcexportMetadata, {"opc_hostname": "opc"}, "o")

    assert config.opc_hostname == "opc"
    assert str(config.elastic_ip) == "172.16.0.254"
    assert config.elastic_port == 9200


def test_elastic_ip_is_a_plain_dotted_string():
    config = parse_metadata(
        OpcexportMetadata, {"opc_hostname": "opc", "elastic_ip": "10.1.2.3"}, "o"
    )
    assert str(config.elastic_ip) == "10.1.2.3"


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({}, "opc_hostname: Field required"),
        ({"opc_hostname": "a"}, "opc_hostname"),
        ({"opc_hostname": "op;reboot"}, "opc_hostname"),
        ({"opc_hostname": "opc", "elastic_ip": "1.2.3.4; calc"}, "elastic_ip"),
        ({"opc_hostname": "opc", "elastic_ip": "elastic"}, "elastic_ip"),
        ({"opc_hostname": "opc", "elastic_port": "9200"}, "elastic_port"),
        ({"opc_hostname": "opc", "elastic_port": 0}, "elastic_port"),
        ({"opc_hostname": "opc", "elastic_port": 65536}, "elastic_port"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(OpcexportMetadata, md, "o")


def test_unknown_key_is_accepted():
    # the model has no nested blocks, so unknown keys are kept without warning
    md = {"opc_hostname": "opc", "bogus": 1}
    config, warnings = validate_metadata(OpcexportMetadata, md, "o")

    assert warnings == []
    assert config.model_extra == {"bogus": 1}


def test_ipv6_elastic_ip_is_rejected():
    with pytest.raises(ValueError, match="elastic_ip"):
        parse_metadata(
            OpcexportMetadata, {"opc_hostname": "opc", "elastic_ip": "::1"}, "o"
        )


class FakeMM:
    def __init__(self):
        self.calls = []

    def cc_filter(self, f):
        self.calls.append(("filter", f))

    def clear_cc_filter(self):
        self.calls.append(("clear",))

    def cc_background_once(self, cmd):
        self.calls.append(("background", cmd))


def component(md, monkeypatch):
    comp = object.__new__(OPCExport)
    comp.name = "opcexport"
    comp.mm = FakeMM()
    comp.config = parse_metadata(OpcexportMetadata, md, "o")
    execs = []
    monkeypatch.setattr(
        utils, "mm_exec_wait", lambda mm, host, cmd, *a, **k: execs.append((host, cmd))
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)
    comp.check_process_running = lambda *a, **k: True
    comp.execs = execs
    return comp


def test_start_builds_the_scada_to_elastic_command(monkeypatch):
    comp = component(
        {"opc_hostname": "opc", "elastic_ip": "10.1.2.3", "elastic_port": 9201},
        monkeypatch,
    )
    comp.start()

    cmd = comp.mm.calls[1][1]
    assert comp.mm.calls[0] == ("filter", "name=opc")
    assert "scada_to_elastic.py -u opc.tcp://opc:4840" in cmd
    assert cmd.endswith("-e 10.1.2.3:9201")


def test_cleanup_builds_the_delete_command(monkeypatch):
    comp = component({"opc_hostname": "opc"}, monkeypatch)
    comp.cleanup()

    assert comp.execs == [
        (
            "opc",
            "C:/Progra~1/Python38/python.exe C:/opcexport/delete_scada_to_elastic.py"
            " -e 172.16.0.254:9200",
        )
    ]


def test_stop_kills_python_and_collects_the_log(monkeypatch):
    comp = component({"opc_hostname": "opc"}, monkeypatch)
    killed, received, deleted = [], [], []
    monkeypatch.setattr(
        utils, "mm_kill_process", lambda mm, **kw: killed.append(kw["cc_filter"])
    )
    monkeypatch.setattr(
        utils, "mm_delete_file", lambda mm, flt, path: deleted.append((flt, path))
    )
    comp.recv_file = lambda host, path: received.append((host, path))
    comp.stop()

    assert killed == ["name=opc"]
    assert received == [("opc", "/opcexport/scada_to_elastic.log")]
    assert deleted == [("name=opc", "/opcexport/scada_to_elastic.log")]
