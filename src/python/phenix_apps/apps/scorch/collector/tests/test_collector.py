import json
from pathlib import Path

import pytest
import yaml
from box import Box

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import validate_metadata
from phenix_apps.apps.scorch.collector.collector import (
    Collector,
    CollectorMetadata,
    _utc_time,
    check_iperf_before_collector,
    enabled_by_type,
)
from phenix_apps.apps.scorch.collector.csv_gen import gen_csv
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_has_examples():
    assert len(readme_components(README, "collector")) == 2


@pytest.mark.parametrize(
    "cmp", readme_components(README, "collector"), ids=lambda c: c["name"]
)
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(CollectorMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_code():
    config, _ = validate_metadata(CollectorMetadata, {}, "c")
    assert config.collect_iperf is False
    assert config.collect_miniccc is False
    assert config.generate_csv is False
    assert config.pcap_duration_margin == 6.0


@pytest.mark.parametrize("value", [None, "maybe", 1.5])
def test_flags_must_be_booleans(value):
    with pytest.raises(ValueError, match="generate_csv"):
        validate_metadata(CollectorMetadata, {"generate_csv": value}, "c")


def test_unknown_key_warns():
    _, warnings = validate_metadata(CollectorMetadata, {"generate_cvs": True}, "c")
    assert "did you mean 'generate_csv'" in warnings[0]


def test_utc_time():
    assert _utc_time("2026-10-13T12:00:00+00:00\n", "f").hour == 12
    with pytest.raises(RuntimeError, match="not a UTC time"):
        _utc_time("2026-10-13T12:00:00+02:00", "f")
    with pytest.raises(RuntimeError, match="not a UTC time"):
        _utc_time("2026-10-13T12:00:00", "f")


def collector(tmp_path: Path, components: list[dict], enabled: list[str]) -> Collector:
    """A Collector with just the state its helpers read; no phenix or minimega."""

    c = Collector.__new__(Collector)
    c.run, c.loop, c.count = 0, 0, 0
    c.files_dir = tmp_path
    c.results_dir = tmp_path / "results"
    c.meta_dir = c.results_dir / "metadata"
    boxed = [Box(cmp) for cmp in components]
    c.all_components = {cmp.type: cmp for cmp in boxed}
    c.enabled_components = {cmp.type: cmp for cmp in boxed if cmp.name in enabled}
    return c


def out_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"scorch/run-0/{name}/loop-0-count-0"
    path.mkdir(parents=True)
    return path


def test_disruption_prerequisites(tmp_path):
    with pytest.raises(ValueError, match="needs a 'disruption' component"):
        collector(tmp_path, [], [])._disruption_metadata()

    dis = {"name": "d", "type": "disruption", "metadata": {"run_duration": 60}}
    with pytest.raises(ValueError, match="missing current_disruption, permutation"):
        collector(tmp_path, [dis], ["d"])._disruption_metadata()


def test_output_dir_of_the_enabled_instance(tmp_path):
    # one disruption per permutation; only the second is in this run
    components = [
        {"name": "dos-0", "type": "disruption"},
        {"name": "dos-1", "type": "disruption"},
        {"name": "dos-2", "type": "disruption"},
    ]
    expected = out_dir(tmp_path, "dos-1")

    assert (
        collector(tmp_path, components, ["dos-1"])._comp_dir("disruption") == expected
    )


def test_output_dir_falls_back_to_the_run_level_folder(tmp_path):
    # a component run in configure, before any loop, only has loop-0-count-0
    expected = out_dir(tmp_path, "rtds")
    c = collector(tmp_path, [{"name": "rtds", "type": "rtds"}], ["rtds"])
    c.loop, c.count = 2, 3

    assert c._comp_dir("rtds") == expected

    with pytest.raises(RuntimeError, match="doesn't exist"):
        collector(tmp_path, [{"name": "x", "type": "x"}], ["x"])._comp_dir("x")


def test_pcap_without_merged_capture_is_collected(tmp_path):
    components = [
        {"name": "d", "type": "disruption", "metadata": {"run_duration": 60}},
        {"name": "p", "type": "pcap"},
    ]
    src = out_dir(tmp_path, "p")
    meta = {"rtu-0.pcap": {"Capture duration (seconds)": "59"}}
    (src / "pcap_metadata.json").write_text(json.dumps(meta))
    c = collector(tmp_path, components, ["d", "p"])
    c.results_dir.mkdir()

    assert c._collect_pcap() == meta


def test_provider_with_pmus_is_collected(tmp_path):
    src = out_dir(tmp_path, "rtds")
    (src / "config.ini").write_text(
        "[power-solver-service]\nsolver-type = RTDS\nconfig-file = /etc/rtds.yaml\n"
    )
    (src / "rtds.yaml").write_text(
        yaml.safe_dump({"pmu": {"pmus": [{"name": "PMU1", "label": "BUS7"}]}})
    )
    c = collector(tmp_path, [{"name": "rtds", "type": "rtds"}], ["rtds"])
    c.meta_dir.mkdir(parents=True)

    data = c._collect_provider_data()

    assert data["simulator"] == "RTDS"
    assert data["pmus"] == {"PMU1": "BUS7"}


def test_empty_provider_config_is_reported(tmp_path):
    src = out_dir(tmp_path, "rtds")
    (src / "config.ini").write_text("  \n")
    c = collector(tmp_path, [{"name": "rtds", "type": "rtds"}], ["rtds"])
    c.meta_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match=r"empty config\.ini"):
        c._collect_provider_data()


def test_enabled_by_type_finds_the_one_this_run_uses():
    components = [Box(name=f"dos-{i}", type="disruption") for i in range(3)] + [
        Box(name="cap", type="pcap"),
        Box(name="unused", type="iperf"),
    ]
    run = Box(
        {
            "configure": [],
            "start": ["dos-1"],
            "stop": [],
            "loop": {"count": 2, "stop": ["cap"]},
        }
    )

    enabled = enabled_by_type(components, run)

    assert {t: c.name for t, c in enabled.items()} == {
        "disruption": "dos-1",
        "pcap": "cap",
    }


@pytest.mark.parametrize(
    ("run", "fails"),
    [
        ({"stop": ["ip", "col"]}, False),
        ({"stop": ["col", "ip"]}, True),
        ({"loop": {"stop": ["col", "ip"]}}, True),
        ({"stop": ["col"]}, False),
        ({"stop": ["ip", "col", "ip2"]}, True),
    ],
)
def test_iperf_must_precede_collector_in_stop(run, fails):
    comps = [
        Box(name="ip", type="iperf"),
        Box(name="ip2", type="iperf"),
        Box(name="col", type="collector"),
    ]
    if fails:
        with pytest.raises(ValueError, match="list iperf first"):
            check_iperf_before_collector(comps, Box(run))
    else:
        check_iperf_before_collector(comps, Box(run))


def test_init_checks_iperf_order(monkeypatch):
    def fake_base_init(self, name):
        self.run, self.base_dir = 0, "/x"
        self.config = CollectorMetadata(collect_iperf=True)
        self.extract_app = lambda _: Box(
            metadata={
                "components": [
                    {"name": "ip", "type": "iperf"},
                    {"name": "col", "type": "collector"},
                ],
                "runs": [{"stop": ["col", "ip"]}],
            }
        )

    monkeypatch.setattr(ComponentBase, "__init__", fake_base_init)
    with pytest.raises(ValueError, match="list iperf first"):
        Collector()


def test_csv_without_pmus_fails_with_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="no PMUs"):
        gen_csv(record={"provider": {}}, csv_path=tmp_path / "x.csv", es_server="")


def test_csv_ignores_the_old_rtds_key(tmp_path):
    with pytest.raises(RuntimeError, match="no PMUs"):
        gen_csv(
            record={"rtds": {"pmus": {"pmu1": "a"}}},
            csv_path=tmp_path / "x.csv",
            es_server="",
        )
