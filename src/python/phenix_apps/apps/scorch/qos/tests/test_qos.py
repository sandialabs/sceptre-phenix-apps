import json
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.qos.qos import QoS, QoSMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def test_readme_has_examples():
    assert len(readme_components(README, "qos")) == 2


@pytest.mark.parametrize(
    "cmp", readme_components(README, "qos"), ids=lambda c: c["name"]
)
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(QoSMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_readme_troubleshooting_errors_match():
    md = {
        "vms": [
            {"hostname": "vm-a", "rate": "1 mbit", "loss": 1},
            {"hostname": "vm-b", "delay": "100x"},
        ]
    }
    with pytest.raises(ValueError, match="2 problem") as exc:
        parse_metadata(QoSMetadata, md, "qos")
    readme = README.read_text()
    assert "vms.N: Value error, rate cannot be combined with loss or delay" in readme
    assert "vms.0: Value error, rate cannot be combined with loss or delay" in str(
        exc.value
    )


@pytest.mark.parametrize(
    ("entry", "field", "value"),
    [
        ({"loss": 25}, "loss", 25.0),
        ({"delay": " 1S "}, "delay", "1s"),
        ({"delay": "1m30s"}, "delay", "1m30s"),
        ({"rate": "500 kbit"}, "rate", "500 kbit"),
        ({"rate": "500kbit"}, "rate", "500 kbit"),  # used to crash on split(" ")
        ({"rate": "1.5  MBIT"}, "rate", "1500 kbit"),  # minimega wants whole numbers
        ({"rate": "0.25 gbit"}, "rate", "250 mbit"),
        ({"rate": "2.0 mbit"}, "rate", "2 mbit"),
        ({"delay": ".5s"}, "delay", ".5s"),
        ({"delay": "1.s"}, "delay", "1.s"),
        ({"delay": 100}, "delay", "100ms"),
        ({"delay": " 1.5 "}, "delay", "1.5ms"),
        ({"delay": ".5"}, "delay", ".5ms"),
        ({"delay": "0"}, "delay", "0ms"),
        ({"delay": "1.5h2.m"}, "delay", "1.5h2.m"),
    ],
)
def test_values_are_normalised(entry, field, value):
    config = parse_metadata(QoSMetadata, {"vms": [{"hostname": "vm-a", **entry}]}, "q")
    assert getattr(config.vms[0], field) == value


def test_variable_loss_works_alone_and_wins_over_loss():
    md = {
        "vms": [
            {"hostname": "vm-a", "variable_loss": 10},  # used to need a dummy loss
            {"hostname": "vm-b", "loss": 50, "variable_loss": 5},
        ]
    }
    config = parse_metadata(QoSMetadata, md, "q")
    assert config.vms[0].loss_for(3) == 30.0
    assert config.vms[1].loss_for(2) == 10.0


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({}, "needs one of loss"),
        ({"rate": "1 mbit", "delay": "1s"}, "rate cannot be combined"),
        ({"rate": "1 mbit", "variable_loss": 1}, "rate cannot be combined"),
        ({"loss": 100}, "less than 100"),
        ({"loss": 99.95}, "loss must be 0.0 to 99.9"),
        ({"loss": "25"}, "valid number"),
        ({"loss": -1}, "loss"),
        ({"rate": "500 kbps"}, "rate"),
        ({"rate": "1.0005 mbit"}, "whole number of kbit"),
        ({"rate": "1.5 kbit"}, "whole number of kbit"),
        ({"delay": "."}, "delay"),
        ({"delay": ".s"}, "delay"),
        ({"delay": True}, "delay"),
        ({"delay": "-5"}, "delay"),
        ({"delay": "1..5s"}, "delay"),
        ({"delay": "1s; reboot"}, "delay"),
        ({"loss": 1, "interface": "eth0 eth1"}, "interface"),
    ],
)
def test_bad_entries_are_rejected(entry, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(QoSMetadata, {"vms": [{"hostname": "vm-a", **entry}]}, "q")


class FakeMinimega:
    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


def qos(tmp_path, md: dict, count: int = 0) -> QoS:
    component = QoS.__new__(QoS)
    component.name = "qos"
    component.count = count
    component.base_dir = tmp_path
    component.mm = FakeMinimega()
    component.config = parse_metadata(QoSMetadata, md, "q")
    nodes = {"vm-a": ["eth0", "eth1"]}
    component.experiment = Box(
        {
            "spec": {
                "topology": {
                    "nodes": [
                        {
                            "general": {"hostname": h},
                            "network": {"interfaces": [{"name": n} for n in ifaces]},
                        }
                        for h, ifaces in nodes.items()
                    ]
                }
            }
        }
    )
    return component


def test_start_applies_and_records(tmp_path):
    md = {
        "vms": [
            {"hostname": "vm-a", "interface": "eth1", "loss": 5, "delay": "10ms"},
        ]
    }
    component = qos(tmp_path, md)
    component.start()

    assert component.mm.calls == [
        ("qos_add_loss", "vm-a", 1, 5.0),
        ("qos_add_delay", "vm-a", 1, "10ms"),
    ]
    applied = json.loads((tmp_path / "qos_values_applied.json").read_text())
    assert applied == {"vm-a": {"interface": 1, "loss": 5.0, "delay": "10ms"}}


def test_variable_loss_past_the_limit_fails_at_that_count(tmp_path):
    component = qos(
        tmp_path, {"vms": [{"hostname": "vm-a", "variable_loss": 50}]}, count=2
    )
    with pytest.raises(ValueError, match=r"loss of 100\.0 for vm-a is not between"):
        component.start()
