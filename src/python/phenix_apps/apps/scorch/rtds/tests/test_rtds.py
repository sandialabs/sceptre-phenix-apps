from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.rtds.rtds import RTDS, RTDSMetadata, get_time_drift
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "rtds")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid(cmp):
    _, warnings = validate_metadata(RTDSMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    config = parse_metadata(RTDSMetadata, {"hostname": "prov"}, "r")

    assert config.export_config is True
    assert config.export_logs is False
    assert config.rscad_automation.enabled is False
    assert config.elasticsearch.verify is False
    assert config.csv_files is None
    assert config.rscad_automation.timeout == 30
    assert config.provider_start_wait == 8.0
    assert config.elasticsearch.doc_count_wait == 3.0
    assert config.elasticsearch.acceptable_time_drift is None


def test_csv_path_defaults():
    md = {"hostname": "prov", "csv_files": {"export": True}}
    config = parse_metadata(RTDSMetadata, md, "r")
    assert config.csv_files is not None
    assert config.csv_files.path == "/root/rtds_data"


@pytest.mark.parametrize("csv_files", [{}, None])
def test_empty_csv_files_skips_csv_handling(csv_files):
    md = {"hostname": "prov", "csv_files": csv_files}
    assert parse_metadata(RTDSMetadata, md, "r").csv_files is None


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "//",
        "/root/..",
        "/root/.",
        "relative/dir",
        "/a b",
        "/*",
        "/root/*",
        "/tmp/x;reboot",
        "/a/$(id)",
        "/a/`id`",
    ],
)
def test_csv_path_that_rm_rf_would_wreck_is_rejected(path):
    md = {"hostname": "prov", "csv_files": {"path": path}}
    with pytest.raises(ValueError, match=r"csv_files\.path"):
        parse_metadata(RTDSMetadata, md, "r")


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"elasticsearch": {"verify": True}}, "server and index required"),
        (
            {"elasticsearch": {"verify": True, "server": "http://es:9200"}},
            "index required",
        ),
        ({"rscad_automation": {"enabled": True}}, "url is required"),
        ({"rscad_automation": {"enabled": True, "url": "ftp://x"}}, "url"),
        # a malformed URL fails even while its feature is off
        ({"rscad_automation": {"url": "172.24.24.120:8000"}}, "rscad_automation.url"),
        ({"elasticsearch": {"server": "es:9200"}}, "elasticsearch.server"),
        ({"rscad_automation": {"timeout": 0}}, "rscad_automation.timeout"),
        ({"elasticsearch": {"acceptable_time_drift": 0}}, "acceptable_time_drift"),
        ({"elasticsearch": {"doc_count_wait": 1}}, "doc_count_wait"),
        ({"provider_start_wait": -1}, "provider_start_wait"),
        ({"hostname": "bad host"}, "hostname"),
        # wrong types are not coerced
        ({"export_logs": None}, "export_logs"),
        ({"export_config": "maybe"}, "export_config"),
        ({"rscad_automation": {"enabled": "maybe"}}, "rscad_automation.enabled"),
        ({"elasticsearch": {"verify": []}}, "elasticsearch.verify"),
        ({"csv_files": {"export": []}}, "csv_files.export"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(RTDSMetadata, {"hostname": "prov", **md}, "r")


@pytest.mark.parametrize(
    ("md", "warning"),
    [
        (
            {"elasticsearch": {"verify_es": True}},
            "elasticsearch.verify_es: unknown key, ignored. Fix: remove it "
            "(did you mean 'verify'?)",
        ),
        (
            {"case_name": "top"},
            "case_name: unknown key, ignored. Fix: remove it",
        ),
    ],
)
def test_unknown_keys_only_warn(md, warning):
    _, warnings = validate_metadata(RTDSMetadata, {"hostname": "prov", **md}, "r")

    assert len(warnings) == 1
    assert warnings[0].startswith(warning)


@pytest.mark.parametrize("name", ["Wanted", "IEEE9BUSMJBLoads2", "case v1.2", "a-b_c"])
def test_valid_case_names(name):
    md = {"rscad_automation": {"case_name": f" {name} "}}
    config = parse_metadata(RTDSMetadata, {"hostname": "prov", **md}, "r")
    assert config.rscad_automation.case_name == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "  ",
        "case.rtfx",
        "CASE.RTF",
        "dir/case",
        "C:\\cases\\case",
        "a:b",
        'a"b',
        "a*b",
        "a?b",
        "a<b",
        "a|b",
        "a\x00b",
        "case.",
        "x" * 256,
        5,
    ],
)
def test_bad_case_names_are_rejected(name):
    md = {"rscad_automation": {"case_name": name}}
    with pytest.raises(ValueError, match=r"rscad_automation\.case_name"):
        parse_metadata(RTDSMetadata, {"hostname": "prov", **md}, "r")


@pytest.mark.parametrize("url", ["http://r:8000", "http://r:8000/"])
def test_rscad_endpoint_has_one_slash(url):
    config = parse_metadata(
        RTDSMetadata,
        {"hostname": "prov", "rscad_automation": {"url": url}},
        "r",
    )
    assert config.rscad_automation.url == "http://r:8000"
    md = {"rscad_automation": {"enabled": True, "url": url}}
    assert rtds(md, FakeSession())._rscad_endpoint("start_case") == (
        "http://r:8000/start_case"
    )


class FakeResponse:
    def __init__(self, status: int, data: dict | None = None):
        self.status_code = status
        self.data = data or {}

    def __bool__(self):
        return self.status_code < 400

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, *responses: FakeResponse):
        self.responses = list(responses)
        self.posts: list[tuple[str, float]] = []

    def post(self, url, timeout):
        self.posts.append((url, timeout))
        return self.responses.pop(0)


def rtds(md: dict, session: FakeSession) -> RTDS:
    """An RTDS with just the state the RSCAD helpers read; no minimega."""

    component = RTDS.__new__(RTDS)
    component.config = parse_metadata(
        RTDSMetadata,
        {"hostname": "prov", "rscad_automation": {"enabled": True, "url": "http://r"}}
        | md,
        "r",
    )
    component.session = session
    return component


def case(name: str, success: bool = True) -> dict:
    return {
        "success": success,
        "case_file": f"C:\\cases\\{name}.rtfx",
        "case_title": name,
        "status": "running" if success else "error",
    }


def test_wrong_case_is_stopped_and_fails():
    md = {
        "rscad_automation": {
            "enabled": True,
            "url": "http://r:8000/",
            "case_name": "Wanted",
            "timeout": 5,
        }
    }
    session = FakeSession(
        FakeResponse(200, case("Other")), FakeResponse(200, case("Other"))
    )

    with pytest.raises(RuntimeError, match="Expected RSCAD case 'Wanted'"):
        rtds(md, session)._start_case()

    assert [url for url, _ in session.posts] == [
        "http://r:8000/start_case",
        "http://r:8000/stop_case",
    ]
    assert [timeout for _, timeout in session.posts] == [5.0, 5.0]


def test_stop_case_failure_raises_unless_allowed():
    with pytest.raises(RuntimeError, match="HTTP 500"):
        rtds({}, FakeSession(FakeResponse(500)))._stop_case()

    # used to fall through to resp.json() and KeyError on 'case_file'
    rtds({}, FakeSession(FakeResponse(500)))._stop_case(allow_failure=True)
    rtds(
        {}, FakeSession(FakeResponse(200, {"success": False, "status": "x"}))
    )._stop_case(allow_failure=True)


class FakeES:
    def search(self, **_):
        return {"aggregations": {"timestamp_diff": {"value": None}}}


def test_time_drift_without_data_fails_clearly():
    with pytest.raises(RuntimeError, match="cannot check time drift"):
        get_time_drift(FakeES(), "rtds-clean-2026.10.13")


def test_configure_waits_provider_start_wait_after_starting_provider(monkeypatch):
    component = rtds(
        {
            "rscad_automation": {"enabled": False},
            "provider_start_wait": 7,
            "elasticsearch": {"doc_count_wait": 4},
        },
        FakeSession(),
    )
    component.name = "r"
    component.ensure_vm_running = lambda _: None
    component.recv_file = lambda **_: None
    component.run_and_check_command = lambda *_: {"stdout": "ok"}
    component.check_process_running = lambda *_: False
    sleeps = []
    monkeypatch.setattr("phenix_apps.apps.scorch.rtds.rtds.sleep", sleeps.append)

    component.configure()

    assert sleeps == [7.0]
