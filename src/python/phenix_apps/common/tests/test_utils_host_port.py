import pytest

from phenix_apps.common import utils


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.0.0.1", ("10.0.0.1", None)),
        ("10.0.0.1:502", ("10.0.0.1", 502)),
        ("eth1:20000", ("eth1", 20000)),
        ("plc-1", ("plc-1", None)),
        ("fe80::1", ("fe80::1", None)),
        ("fe80::", ("fe80::", None)),
        ("[fe80::1]:502", ("fe80::1", 502)),
        ("[fe80::1]", ("fe80::1", None)),
    ],
)
def test_split_host_port(value, expected):
    assert utils.split_host_port(value) == expected


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("", "no host"),
        (":502", "no host"),
        ("[]:502", "no host"),
        ("10.0.0.1:", "invalid port"),
        ("10.0.0.1:http", "invalid port"),
        ("10.0.0.1:0", "invalid port"),
        ("10.0.0.1:65536", "invalid port"),
        ("[fe80::1]:", "invalid port"),
        ("[fe80::1", "malformed address"),
        ("[fe80::1]502", "malformed address"),
    ],
)
def test_split_host_port_rejects_malformed_input(value, error):
    with pytest.raises(ValueError, match=error):
        utils.split_host_port(value)
