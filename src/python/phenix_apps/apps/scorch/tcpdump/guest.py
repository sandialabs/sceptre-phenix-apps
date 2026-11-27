"""tcpdump captures inside VMs through miniccc, shared by the tcpdump and pcap
components."""

import shlex
from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Args, FilterExpr
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# options and filter are shell-quoted into the launcher script sent to the guest
# (hence no single quotes); empty means none
GuestOptions = Annotated[Args, StringConstraints(strip_whitespace=True)]
GuestFilter = Annotated[FilterExpr, StringConstraints(strip_whitespace=True)]


def start_capture(
    component: ComponentBase,
    hostname: str,
    iface: str,
    options: str = "",
    bpf: str = "",
) -> None:
    """Start tcpdump on `iface` in the VM, writing /dump-<iface>.pcap there."""

    pcap = f"/dump-{iface}.pcap"
    pidfile = f"/dump-{iface}.pid"
    errfile = f"/dump-{iface}.err"
    mm = component.mm

    # mm_exec_wait raises if the VM does not exist or its miniccc client
    # never registers, which covers "VM is not running".
    res = utils.mm_exec_wait(mm, hostname, "which tcpdump")
    if not res["stdout"]:
        raise RuntimeError(f"tcpdump is not installed in VM {hostname}")

    # "any" is tcpdump's every-interface pseudo-device, not a link
    if iface != "any":
        res = utils.mm_exec_wait(mm, hostname, f"ip link show {iface}")
        if res["exitcode"] != 0:
            raise RuntimeError(f"interface {iface} does not exist in VM {hostname}")

    # a pid file left by a failed stop or cleanup; stop its tcpdump so
    # the new capture does not fight it over the file. minimega expands
    # a bare $name in an inline cc command (to nothing), so only
    # $(...) is used here; anything else goes through a script file.
    res = utils.mm_exec_wait(
        mm,
        hostname,
        f"bash -c 'if [ -s {pidfile} ] && "
        f"[ $(cat /proc/$(cat {pidfile})/comm) = tcpdump ]; "
        f"then kill $(cat {pidfile}); echo killed; fi; rm -f {pidfile}'",
    )
    if res["stdout"]:
        logger.warning(
            f"stopped a tcpdump left running in VM {hostname} by an "
            f"earlier run ({pidfile})"
        )

    logger.info(f"starting tcpdump on interface {iface} in VM {hostname}")

    if bpf:
        logger.debug(f"using filter {bpf} for tcpdump in VM {hostname}")

    # exec keeps the shell's PID for tcpdump, so the pid file is
    # tcpdump's; its stderr goes to a file in the VM, or a startup
    # failure would be invisible
    args = [*map(shlex.quote, shlex.split(options))]
    args += ["-i", iface, "-U", "-w", pcap]
    if bpf:
        args.append(shlex.quote(bpf))
    launcher = send_script(
        component,
        hostname,
        f"tcpdump_{hostname}_{iface}.sh",
        f"echo $$ > {pidfile}\nexec tcpdump {' '.join(args)} 2> {errfile}\n",
    )

    utils.mm_cc_filter_vm(mm, hostname)
    if iface != "any":
        mm.cc_exec(f"ip link set {iface} up")
    mm.cc_background(f"bash {launcher}")


def stop_capture(component: ComponentBase, hostname: str, iface: str, dst: str) -> None:
    """Stop the tcpdump started by start_capture, copy its capture to `dst` and
    delete the capture, PID file and stderr file from the VM."""

    pidfile = f"/dump-{iface}.pid"
    mm = component.mm

    res = utils.mm_exec_wait(mm, hostname, f"bash -c 'kill $(cat {pidfile})'")
    if res["exitcode"] != 0:
        # the capture may be incomplete, but it is still worth collecting
        logger.error(
            f"could not stop tcpdump in VM {hostname} using {pidfile}: {res['stderr']}"
        )

    logger.info(f"copying PCAP file from node {hostname}...")

    utils.mm_recv(mm, hostname, f"/dump-{iface}.pcap", dst)
    # target the VM explicitly (by UUID, like the helpers above); this
    # used to rely on whichever filter they happened to leave behind
    utils.mm_cc_filter_vm(mm, hostname)
    mm.cc_exec(f"rm -f /dump-{iface}.pcap {pidfile} /dump-{iface}.err")
    mm.clear_cc_filter()

    logger.info(f"done copying PCAP file from node {hostname}")


def send_script(component: ComponentBase, hostname: str, name: str, body: str) -> str:
    """Send a script to the VM via cc; return its path there.

    Like the cc component: a script file is not subject to minimega's
    expansion of $name, which an inline command is.
    """

    src = Path(component.root_dir) / component.exp_name / name
    src.write_text("#!/bin/bash\n" + body)
    try:
        utils.mm_cc_send_wait(component.mm, hostname, str(src), component.exp_name)
    finally:
        component.mm.clear_cc_filter()
        src.unlink(missing_ok=True)

    return f"/tmp/miniccc/files/{component.exp_name}/{name}"
