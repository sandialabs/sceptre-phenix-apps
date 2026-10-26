from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.ettercap.ettercap import Ettercap, EttercapMetadata
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "ettercap")


def test_readme_has_examples():
    assert len(readme_examples()) == 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(EttercapMetadata, cmp["metadata"], cmp["name"])
    assert warnings == []


def test_method_defaults_to_arp():
    config = parse_metadata(
        EttercapMetadata,
        {"vms": [{"hostname": "attacker", "interface": "eth0", "targets": "/10.0.0.1//"}]},
        "e",
    )
    assert config.vms[0].method == "arp"


@pytest.mark.parametrize(
    "method",
    [
        "arp",
        "icmp",
        "dhcp",
        "port",
        "ndp",
        "arp:remote",
        "icmp:aa:bb/10.0.0.1",
        "arp:remote,oneway",
        "dhcp:192.168.0.30,35,50-60/255.255.255.0/10.0.0.1",
    ],
)
def test_valid_methods(method):
    md = {
        "vms": [
            {
                "hostname": "aa",
                "interface": "eth0",
                "targets": "/10.0.0.1//",
                "method": method,
            }
        ]
    }
    assert parse_metadata(EttercapMetadata, md, "e").vms[0].method == method


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({}, "vms: Field required"),
        ({"vms": []}, "vms: List should have at least 1 item"),
        ({"vms": [{"interface": "eth0", "targets": "/10.0.0.1//"}]}, r"vms\.0\.hostname"),
        ({"vms": [{"hostname": "aa", "targets": "/10.0.0.1//"}]}, r"vms\.0\.interface"),
        ({"vms": [{"hostname": "aa", "interface": "eth0"}]}, r"vms\.0\.targets"),
        (
            {
                "vms": [
                    {"hostname": "a;reboot", "interface": "eth0", "targets": "/10.0.0.1//"}
                ]
            },
            r"vms\.0\.hostname",
        ),
        (
            {"vms": [{"hostname": "aa", "interface": "x" * 16, "targets": "/10.0.0.1//"}]},
            r"vms\.0\.interface",
        ),
        (
            {"vms": [{"hostname": "aa", "interface": "eth0", "targets": ""}]},
            r"vms\.0\.targets",
        ),
        (
            {
                "vms": [
                    {
                        "hostname": "aa",
                        "interface": "eth0",
                        "targets": "/10.0.0.1//",
                        "method": "evil",
                    }
                ]
            },
            r"vms\.0\.method",
        ),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(EttercapMetadata, md, "e")


@pytest.mark.parametrize(
    "bad",
    [
        "/10.0.0.1// ; reboot",
        "/10.0.0.1//; pkill ettercap",
        "/10.0.0.1// && rm -rf /",
        "$(id)",
        "`id`",
        "/10.0.0.1//\nreboot",
        "-D /10.0.0.1//",
        "/10.0.0.1// -D",
    ],
)
def test_targets_that_carry_shell_syntax_are_rejected(bad):
    md = {"vms": [{"hostname": "aa", "interface": "eth0", "targets": bad}]}
    with pytest.raises(ValueError, match=r"vms\.0\.targets"):
        parse_metadata(EttercapMetadata, md, "e")


def test_same_host_interface_twice_is_rejected():
    md = {
        "vms": [
            {"hostname": "aa", "interface": "eth0", "targets": "/10.0.0.1//"},
            {"hostname": "aa", "interface": "eth0", "targets": "/10.0.0.2//"},
        ]
    }
    with pytest.raises(ValueError, match="started more than once on: aa eth0"):
        parse_metadata(EttercapMetadata, md, "e")


def test_same_host_different_interface_is_allowed():
    md = {
        "vms": [
            {"hostname": "aa", "interface": "eth0", "targets": "/10.0.0.1//"},
            {"hostname": "aa", "interface": "eth1", "targets": "/10.0.0.2//"},
        ]
    }
    assert len(parse_metadata(EttercapMetadata, md, "e").vms) == 2


def test_unknown_vm_key_only_warns():
    md = {
        "vms": [
            {
                "hostname": "aa",
                "interface": "eth0",
                "targets": "/10.0.0.1//",
                "bogus": "arp",
            }
        ]
    }
    _, warnings = validate_metadata(EttercapMetadata, md, "e")
    assert warnings == [
        "vms.0.bogus: unknown key, ignored. Fix: remove it "
        "(known: hostname, interface, targets, method)"
    ]


def _component(vms):
    cmp = object.__new__(Ettercap)  # skip __init__: it reads argv and stdin
    cmp.name = "e"
    cmp.config = parse_metadata(EttercapMetadata, {"vms": vms}, "e")
    mm = MagicMock()
    return cmp, mm, patch.object(Ettercap, "mm_init", return_value=mm)


def test_start_and_stop_emit_expected_commands():
    cmp, mm, mock = _component(
        [
            {"hostname": "aa", "interface": "eth0", "targets": "/10.0.0.1//"},
            {
                "hostname": "bb",
                "interface": "eth1",
                "targets": "/10.0.0.2// /10.0.0.3//",
                "method": "arp:remote,oneway",
            },
        ]
    )
    with mock:
        cmp.start()
        assert mm.method_calls == [
            call.cc_filter("name=aa"),
            call.cc_exec("ip link set eth0 up"),
            call.cc_background("ettercap -Tq -i eth0 -M arp /10.0.0.1//"),
            call.clear_cc_filter(),
            call.cc_filter("name=bb"),
            call.cc_exec("ip link set eth1 up"),
            call.cc_background(
                "ettercap -Tq -i eth1 -M arp:remote,oneway /10.0.0.2// /10.0.0.3//"
            ),
            call.clear_cc_filter(),
        ]
        mm.reset_mock()
        cmp.stop()
        assert mm.method_calls == [
            call.cc_filter("name=aa"),
            call.cc_exec("pkill ettercap"),
            call.clear_cc_filter(),
            call.cc_filter("name=bb"),
            call.cc_exec("pkill ettercap"),
            call.clear_cc_filter(),
        ]
