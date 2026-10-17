from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.providerdata.providerdata import (
    ProviderData,
    ProviderDataMetadata,
)
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_example_is_valid_and_clean():
    (cmp,) = readme_components(README, "providerdata", "Example")
    _, warnings = validate_metadata(ProviderDataMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_defaults_and_empty_csv_files():
    md = {"hostname": "prov", "csv_files": {}}
    config, warnings = validate_metadata(ProviderDataMetadata, md, "prov")

    assert warnings == []
    assert config.export_config is True
    assert config.export_logs is False
    assert config.csv_files is None
    assert config.elasticsearch.verify is False
    assert config.start_wait == 8.0
    assert config.elasticsearch.min_documents == 100


def test_csv_path_trailing_slash_normalized():
    md = {"hostname": "prov", "csv_files": {"path": "/root/data//"}}
    config, _ = validate_metadata(ProviderDataMetadata, md, "prov")
    assert config.csv_files.path == "/root/data"


def test_csv_files_defaults():
    md = {"hostname": "prov", "csv_files": {"export": True}}
    config = parse_metadata(ProviderDataMetadata, md, "prov")
    assert config.csv_files is not None
    assert config.csv_files.path == "/root/provider_data"


def test_unknown_key_only_warns():
    md = {"hostname": "prov", "elasticsearch": {"verify_es": True}}
    _, warnings = validate_metadata(ProviderDataMetadata, md, "prov")
    assert warnings == [
        "elasticsearch.verify_es: unknown key, ignored. Fix: remove it "
        "(did you mean 'verify'?)"
    ]


def test_server_is_a_url():
    md = {"hostname": "prov", "elasticsearch": {"server": "http://es:9200"}}
    config = parse_metadata(ProviderDataMetadata, md, "prov")
    assert config.elasticsearch.server is not None
    assert config.elasticsearch.server.host == "es"


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"hostname": None}, "hostname"),
        ({"hostname": "bad host"}, "hostname"),
        ({"elasticsearch": {"verify": True}}, "server and index required"),
        # a malformed URL fails even while verify is off
        ({"elasticsearch": {"server": "es:9200"}}, r"elasticsearch\.server"),
        (
            {"elasticsearch": {"verify": True, "server": "es", "index": "i"}},
            r"elasticsearch\.server",
        ),
        ({"csv_files": {"path": "/root/my data"}}, r"csv_files\.path"),
        ({"csv_files": {"path": "/root/$HOME"}}, r"csv_files\.path"),
        ({"csv_files": {"path": "/root/it's"}}, r"csv_files\.path"),
        ({"csv_files": {"path": '/root/"x"'}}, r"csv_files\.path"),
        ({"csv_files": {"path": "root/data"}}, r"csv_files\.path"),
        ({"csv_files": {"path": "/root/../etc"}}, r"csv_files\.path"),
        ({"csv_files": {"growth_wait": 0}}, r"csv_files\.growth_wait"),
        ({"start_wait": -1}, "start_wait"),
        ({"elasticsearch": {"min_documents": 0}}, r"elasticsearch\.min_documents"),
        (
            {"elasticsearch": {"min_new_documents": 0}},
            r"elasticsearch\.min_new_documents",
        ),
        ({"elasticsearch": {"doc_count_wait": 0}}, r"elasticsearch\.doc_count_wait"),
        (
            {"elasticsearch": {"expected_frequency": "sixty"}},
            r"elasticsearch\.expected_frequency",
        ),
        # wrong types are not coerced
        ({"export_logs": None}, "export_logs"),
        ({"export_config": "maybe"}, "export_config"),
        ({"elasticsearch": {"verify": []}}, r"elasticsearch\.verify"),
        ({"elasticsearch": None}, "elasticsearch"),
        ({"csv_files": {"export": []}}, r"csv_files\.export"),
        ({"csv_files": []}, "csv_files"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(ProviderDataMetadata, {"hostname": "prov", **md}, "prov")


def test_config_without_the_config_file_entry_is_named(tmp_path):
    received = []

    def recv_file(vm, src):
        received.append(src)
        (tmp_path / "config.ini").write_text("[other]\nkey = value\n")

    component = ProviderData.__new__(ProviderData)
    component.base_dir = tmp_path
    component.recv_file = recv_file

    with pytest.raises(RuntimeError, match=r"does not name the provider's config file"):
        component._export_config("power-provider")
    assert received == ["/etc/sceptre/config.ini"]


def test_config_export_fetches_the_named_yaml(tmp_path):
    received = []

    def recv_file(vm, src):
        received.append(src)
        (tmp_path / "config.ini").write_text(
            "[power-solver-service]\nconfig-file = /etc/sceptre/opalrt_config.yaml\n"
        )

    component = ProviderData.__new__(ProviderData)
    component.base_dir = tmp_path
    component.recv_file = recv_file

    component._export_config("power-provider")
    assert received == ["/etc/sceptre/config.ini", "/etc/sceptre/opalrt_config.yaml"]


class FakeES:
    def __init__(self, counts, frequency=60.0):
        self.counts = iter(counts)
        self.frequency = frequency
        self.indices = self

    def stats(self, index):
        return {"indices": {index: {"total": {"docs": {"count": next(self.counts)}}}}}

    def search(self, **kwargs):
        return {
            "hits": {
                "hits": [{"_source": {"measurement": {"frequency": self.frequency}}}]
            }
        }


def es_component(monkeypatch, es, **es_md):
    monkeypatch.setattr(
        "phenix_apps.apps.scorch.providerdata.providerdata.sleep", lambda s: None
    )
    component = ProviderData.__new__(ProviderData)
    component.es = es
    component.config = parse_metadata(
        ProviderDataMetadata, {"hostname": "prov", "elasticsearch": es_md}, "p"
    )
    return component


def test_doc_rate(monkeypatch):
    component = es_component(monkeypatch, FakeES([100, 400]), min_new_documents=300)
    component._verify_doc_rate("i", 300)

    component = es_component(monkeypatch, FakeES([100, 399]), min_new_documents=300)
    with pytest.raises(RuntimeError, match="only 299 new documents in i"):
        component._verify_doc_rate("i", 300)


def test_frequency(monkeypatch):
    component = es_component(monkeypatch, FakeES([], 50.2), expected_frequency=50)
    component._verify_frequency("i", 50.0)

    component = es_component(monkeypatch, FakeES([], 59.4), expected_frequency=60)
    with pytest.raises(RuntimeError, match=r"expected 60.0 \+-0.5, got 59.4"):
        component._verify_frequency("i", 60.0)


def test_csv_growth(monkeypatch):
    monkeypatch.setattr(
        "phenix_apps.apps.scorch.providerdata.providerdata.sleep", lambda s: None
    )
    sizes = iter(["100\n200\n", "100\n250\n", "5\n", "5\n"])
    component = ProviderData.__new__(ProviderData)
    component.run_and_check_command = lambda host, cmd: {"stdout": next(sizes)}
    component._verify_csv_growth("p", "/d", 3.0)
    with pytest.raises(RuntimeError, match=r"did not grow in 3\.0 seconds"):
        component._verify_csv_growth("p", "/d", 3.0)
