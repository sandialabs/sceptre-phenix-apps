from unittest.mock import MagicMock

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.scorch.snort.snort import Snort


def component(mocker, iface="eth1", running=True, link_ok=True) -> Snort:
    sn = Snort.__new__(Snort)
    sn.name = "snort"
    sn.metadata = Box({"hostname": "ids", "sniffInterface": iface, "startupWait": 0})
    sn.mm = mm = MagicMock()
    mocker.patch.object(sn, "mm_init", return_value=mm)

    def run(vm, cmd, **_):
        if cmd.startswith("ip link show") and not link_ok:
            raise RuntimeError(
                f"failed to run '{cmd}'\nstderr: Device \"{iface}\" does not exist."
            )
        return {
            "stdout": "ERROR: cannot parse snort.conf\n"
            if cmd.startswith("cat")
            else ""
        }

    mocker.patch.object(sn, "run_and_check_command", side_effect=run)
    mocker.patch.object(sn, "check_process_running", return_value=running)
    return sn


def test_start_runs_snort_with_stderr_captured(mocker):
    sn = component(mocker)
    sn.start()

    (cmd,), _ = sn.mm.cc_background.call_args
    assert cmd == (
        "bash -c 'snort -i eth1 -c /etc/snort/snort.conf 2> /var/log/snort/snort.err'"
    )
    sn.check_process_running.assert_called_once_with("ids", "snort")


def test_start_fails_on_missing_interface(mocker):
    sn = component(mocker, link_ok=False)

    with pytest.raises(RuntimeError, match="sniffInterface eth1 not found on ids"):
        sn.start()

    sn.mm.cc_background.assert_not_called()


def test_start_fails_with_stderr_when_snort_dies(mocker):
    sn = component(mocker, running=False)

    with pytest.raises(RuntimeError, match=r"cannot parse snort\.conf"):
        sn.start()


@pytest.mark.parametrize("iface", ["any'; reboot; '", "eth0 eth1", ""])
def test_start_rejects_unsafe_interface(mocker, iface):
    sn = component(mocker, iface=iface)

    with pytest.raises(ValidationError):
        sn.start()

    sn.mm.cc_background.assert_not_called()
