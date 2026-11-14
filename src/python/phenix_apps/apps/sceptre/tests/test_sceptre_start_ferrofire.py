from pathlib import Path

from mako.template import Template

TEMPLATE = Path(__file__).parents[1] / "templates" / "sceptre_start.mako"


def render(metadata):
    return Template(filename=str(TEMPLATE)).render(
        name="field-device",
        os="linux",
        ips=[{"address": "10.1.1.101", "vlan": "ICS"}],
        metadata=metadata,
        needrestart=False,
        needsleep=False,
    )


def test_ferrofire_branch():
    out = render({"firmware": "ferrofire"})
    assert "/usr/sbin/ferrofire-rtu-start /etc/sceptre/config.xml" in out
    assert "bennu-watcherd" not in out
    assert "service ssh restart" not in out


def test_bennu_unchanged():
    out = render({})
    assert "bennu-watcherd" in out
    assert "ferrofire-rtu-start" not in out
