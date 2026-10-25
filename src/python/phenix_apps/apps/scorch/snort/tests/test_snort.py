from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.snort import snort as snort_mod
from phenix_apps.apps.scorch.snort.snort import Snort, SnortMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "snort")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(SnortMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    config = parse_metadata(SnortMetadata, {}, "s")

    assert config.hostname == "detector"
    assert config.sniffInterface == "eth0"
    assert config.waitDuration == 30.0
    assert config.configs == []
    assert config.scripts.configSnort is None


def test_a_config_entry_parses():
    md = {"configs": [{"src": "/a/b.conf", "dst": "/etc/snort/snort.conf"}]}
    config = parse_metadata(SnortMetadata, md, "s")

    assert config.configs[0].src == "/a/b.conf"
    assert config.configs[0].dst == "/etc/snort/snort.conf"
    assert config.configs[0].name is None


def test_config_name_label_is_accepted():
    md = {"configs": [{"name": "rules", "src": "/a/b.rules", "dst": "/c.rules"}]}
    config = parse_metadata(SnortMetadata, md, "s")
    assert config.configs[0].name == "rules"


def test_configsnort_script_parses():
    md = {"scripts": {"configSnort": {"executor": "bash", "script": "/a/setup.sh"}}}
    script = parse_metadata(SnortMetadata, md, "s").scripts.configSnort

    assert script is not None
    assert script.executor == "bash"
    assert script.script == "/a/setup.sh"


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"hostname": "a;reboot"}, "hostname"),
        ({"sniffInterface": "x" * 16}, "sniffInterface"),
        ({"waitDuration": -1}, "waitDuration"),
        ({"waitDuration": "soon"}, "waitDuration"),
        ({"configs": [{"dst": "/x"}]}, r"configs\.0\.src"),
        ({"configs": [{"src": "/x"}]}, r"configs\.0\.dst"),
        ({"configs": [{"src": "a b", "dst": "/x"}]}, r"configs\.0\.src"),
        (
            {"scripts": {"configSnort": {"script": "/a.sh"}}},
            r"scripts\.configSnort\.executor",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(SnortMetadata, md, "s")


def test_unknown_key_in_a_config_entry_only_warns():
    md = {"configs": [{"src": "/a", "dst": "/b", "bogus": 1}]}
    _, warnings = validate_metadata(SnortMetadata, md, "s")
    assert warnings == [
        "configs.0.bogus: unknown key, ignored. Fix: remove it (known: src, dst, name)"
    ]


class FakeMM:
    def __init__(self, calls):
        self.calls = calls

    def cc_filter(self, f):
        self.calls.append(("filter", f))

    def cc_exec(self, cmd):
        self.calls.append(("exec", cmd))

    def cc_background(self, cmd):
        self.calls.append(("background", cmd))


@pytest.fixture
def stage(monkeypatch, tmp_path):
    """Build a Snort with a recording mm; returns (component, calls)."""
    calls: list[tuple] = []
    comp = object.__new__(Snort)
    comp.name, comp.base_dir = "snort", tmp_path
    comp.mm_init = lambda: FakeMM(calls)

    def send(mm, vm, src, dst):
        calls.append(("send", vm, src, dst))

    def recv(mm, vm, src, dst):
        calls.append(("recv", vm, src, str(dst)))

    monkeypatch.setattr(snort_mod.utils, "mm_send", send)
    monkeypatch.setattr(snort_mod.utils, "mm_recv", recv)
    monkeypatch.setattr(snort_mod.time, "sleep", lambda s: calls.append(("sleep", s)))
    return comp, calls


def test_configure_sends_script_and_configs_then_raises_the_interface(stage):
    comp, calls = stage
    comp.config = parse_metadata(
        SnortMetadata,
        {
            "hostname": "ids",
            "sniffInterface": "eth1",
            "configs": [{"src": "/a/snort.conf", "dst": "/etc/snort/snort.conf"}],
            "scripts": {"configSnort": {"executor": "bash", "script": "/a/setup.sh"}},
        },
        "s",
    )

    comp.configure()

    assert calls == [
        ("send", "ids", "/a/setup.sh", "setup.sh"),
        ("filter", "name=ids"),
        ("exec", "bash /setup.sh"),
        ("send", "ids", "/a/snort.conf", "/etc/snort/snort.conf"),
        ("filter", "name=ids"),
        ("exec", "ip link set eth1 up"),
    ]


def test_start_clears_logs_then_runs_snort_in_the_background(stage):
    comp, calls = stage
    comp.config = parse_metadata(SnortMetadata, {"sniffInterface": "eth1"}, "s")

    comp.start()

    assert calls == [
        ("filter", "name=detector"),
        ("exec", "rm -rf /var/log/snort"),
        ("exec", "mkdir -p /var/log/snort"),
        ("filter", "name=detector"),
        ("background", "snort -i eth1 -c /etc/snort/snort.conf"),
    ]


def test_stop_waits_signals_snort_and_pulls_the_logs(stage, tmp_path):
    comp, calls = stage
    comp.config = parse_metadata(SnortMetadata, {"waitDuration": 5}, "s")

    comp.stop()

    assert calls[:3] == [
        ("sleep", 5.0),
        ("filter", "name=detector"),
        ("exec", "pkill -INT snort"),
    ]
    assert [c[2] for c in calls[3:]] == [
        f"/var/log/snort/{n}" for n in ("alert", "snort.log", "snort.stats")
    ]


def test_stop_converts_snort_stats_to_jsonl(stage, tmp_path):
    comp, _ = stage
    comp.config = parse_metadata(SnortMetadata, {}, "s")
    (tmp_path / "snort.stats").write_text("# comment\n#time,pkts\n1,2\n3,4\n")

    comp.stop()

    out = (tmp_path / "snort-stats.jsonl").read_text().splitlines()
    assert out == ['{"time": "1", "pkts": "2"}', '{"time": "3", "pkts": "4"}']


@pytest.mark.parametrize("content", ["", "# only a comment\n"])
def test_stop_skips_conversion_for_a_short_snort_stats(stage, tmp_path, content):
    comp, _ = stage
    comp.config = parse_metadata(SnortMetadata, {}, "s")
    (tmp_path / "snort.stats").write_text(content)

    comp.stop()  # used to raise IndexError

    assert not (tmp_path / "snort-stats.jsonl").exists()
