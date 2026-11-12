"""Tests for SceptreMetadataParser."""

from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.sceptre.metadata import SceptreMetadataParser
from phenix_apps.common import error


def test_register_overrides_survive_the_parser():
    """The point of the parser fix: overrides reach create_device.

    They used to crash it -- keys were popped while iterating a live dict view
    -- which made the per-device overrides the infrastructure table honours
    unusable.
    """
    parsed = SceptreMetadataParser(
        Box(
            {
                "infrastructure": "power-transmission",
                "provider": "provider-1",
                "dnp3": [{"type": "bus", "name": "bus-1", "analog-read": ["voltage"]}],
            }
        )
    )

    assert parsed.devices_by_protocol == {
        "dnp3": [{"type": "bus", "name": "bus-1", "analog-read": ["voltage"]}]
    }


def test_unknown_device_keys_are_dropped():
    """Only type, name and the four override keys survive the parser.

    Anything else would arrive as a stray create_device kwarg. Validation
    reports it; the parser just does not pass it on.
    """
    parsed = SceptreMetadataParser(
        Box(
            {
                "infrastructure": "power-transmission",
                "provider": "provider-1",
                "dnp3": [{"type": "bus", "name": "bus-1", "analog-reed": ["voltage"]}],
            }
        )
    )

    assert parsed.devices_by_protocol == {"dnp3": [{"type": "bus", "name": "bus-1"}]}


def test_only_collects_known_protocols():
    parsed = SceptreMetadataParser(
        Box(
            {
                "infrastructure": "hvac",
                "provider": "provider-1",
                "modbus": [{"type": "load", "name": "load-1"}],
                "cycle_time": 1000,
                "not-a-protocol": [{"type": "x", "name": "y"}],
            }
        )
    )

    assert list(parsed.devices_by_protocol) == ["modbus"]


def test_missing_required_key_raises_app_error():
    with pytest.raises(error.AppError, match="Failed when parsing metadata"):
        SceptreMetadataParser(Box({"provider": "provider-1"}))  # no infrastructure


def test_ferrofire_templates_render():
    """The provider config names the model; the start script launches ferrofire,
    not the pybennu daemon that a 'provider' hostname would otherwise select."""

    from mako.template import Template

    base = Path(__file__).parent.parent / "templates"
    ini = Template(filename=str(base / "provider_config.mako")).render(
        solver="Ferrofire",
        server_endpoint="tcp://10.0.0.1:5555",
        publish_endpoint="udp://*;239.0.0.1:40000",
        model_file="/etc/sceptre/model.yaml",
    )
    assert "solver-type       = Ferrofire" in ini
    assert "model-file        = /etc/sceptre/model.yaml" in ini

    start = Template(filename=str(base / "sceptre_start.mako")).render(
        os="linux",
        ips=[],
        name="provider",
        metadata={"simulator": "Ferrofire"},
        server_endpoint="tcp://10.0.0.1:5555",
        publish_endpoint="udp://*;239.0.0.1:40000",
        needsleep=False,
        needrestart=False,
    )
    assert (
        "ferrofire run /etc/sceptre/model.yaml --server 'tcp://10.0.0.1:5555'" in start
    )
    assert "pybennu" not in start
