import csv
import datetime
import json
import math
import os
import os.path
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import warnings
from io import StringIO
from pathlib import Path
from socket import inet_ntoa
from struct import pack
from typing import IO

import mako.lookup
import mako.template
import minimega
from elasticsearch import Elasticsearch

import phenix_apps.common.settings as phenix_settings
from phenix_apps.common.logger import logger


def utc_now() -> datetime.datetime:
    """
    This simple helper function ensures a proper UTC-aware timestamp is returned.

    Further reading: https://blog.miguelgrinberg.com/post/it-s-time-for-a-change-datetime-utcnow-is-now-deprecated
    """
    return datetime.datetime.now(datetime.UTC)


def kibana_format_time(ts: datetime.datetime) -> str:
    return ts.strftime("%b %d, %Y @ %H:%M:%S.%f").replace(".000000", ".000")


def mako_render(script_path: str, **kwargs) -> str:
    """Generate a mako template from a file and render it using provided args.

    Args:
        script_path (str): Full path to mako template script.
        kwargs: Arbitrary keyword arguments.

    Returns:
        str: Rendered string from mako template.
    """

    template = mako.template.Template(filename=script_path)

    return template.render(**kwargs)


def mako_serve_template(
    template_name: str, templates_dir: str | Path, filename: IO, **kwargs
) -> None:
    """Serve Mako template.

    This function is based on Mako-style functionality of searching for the template in
    in the template directory and rendering it.

    Args:
        template_name: name of the template
        filename: open file handle to write to (NOT the name of the file)
        kwargs: Arbitrary keyword arguments to pass to the template
    """

    mylookup = mako.lookup.TemplateLookup(directories=[templates_dir])
    mytemplate = mylookup.get_template(template_name)

    # print is a workaround for different encodings, I think
    print(mytemplate.render(**kwargs), file=filename)


def mark_executable(file_path: str) -> None:
    """
    Add executable by owner bit to file mode.
    """
    st_ = os.stat(file_path)
    os.chmod(file_path, st_.st_mode | stat.S_IEXEC)


def generate_mac_addr() -> str:
    """Generates a random MAC address.

    Returns:
        string: The MAC address as a string.
    """

    return ":".join(
        f"{x:02x}"
        for x in [
            0x00,
            0x16,
            0x3E,
            random.randint(0x00, 0x7F),
            random.randint(0x00, 0xFF),
            random.randint(0x00, 0xFF),
        ]
    )


def validate_mac_addr(macs: list[str]) -> bool:
    """Check if MAC address is valid.

    Simple check to see if the MAC looks right.

    Args:
        macs (list): List of MAC addresses in format "xx:xx:xx:xx:xx:xx".

    Returns:
        bool: True if all MACs are valid, otherwise False.
    """

    for mac in macs:
        if len(mac.strip()) != 17 or mac.count(":") != 5:
            return False

    return True


def abs_path(file_: str, relative_path: str | None = None) -> str | Path:
    """Return absolute path to file_ with optional relative resource.

    Args:
        file_ (str): Name of file.
        relative_path (str): Optional relative path of resource.

    Returns:
        str: Full path to file_ (and optional relative resource).
    """

    base_path = Path(file_).parent.absolute()
    return f"{base_path}/{relative_path}" if relative_path else base_path


def cidr_to_netmask(cidr: int) -> str:
    """Convert CIDR notation (24) to a subnet mask (255.255.255.0)"""

    cidr = int(cidr)
    bits = 0xFFFFFFFF ^ (1 << 32 - cidr) - 1

    return inet_ntoa(pack(">I", bits))


def netmask_to_cidr(netmask: str) -> int:
    """Convert netmask (255.255.255.0) to CIDR notation (24)"""

    return sum([bin(int(x)).count("1") for x in netmask.split(".")])


def hms_to_timedelta(uptime: str) -> str:
    """Convert XXhXXmXXs string to a time delta.

    Args:
        uptime (str): string delta time in hms format.

    Returns:
        str: time delta as a pretty string.
    """
    timedelta = None
    if "ms" in uptime:
        temp = uptime.split("ms")
        ms = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(milliseconds=ms)
    elif "h" in uptime:
        temp = uptime.split("h")
        hrs = int(temp[0])
        temp = temp[1].split("m")
        minutes = int(temp[0])
        temp = temp[1].split("s")
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(hours=hrs, minutes=minutes, seconds=sec)
    elif "m" in uptime:
        temp = uptime.split("m")
        minutes = int(temp[0])
        temp = temp[1].split("s")
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(minutes=minutes, seconds=sec)
    elif "s" in uptime:
        temp = uptime.split("s")
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(seconds=sec)
    return str(timedelta)


SECONDS_PER_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def convert_to_seconds(time: str) -> str:
    """Convert time string to seconds (e.g. 30s, 24h).

    Args:
        time (str): time string.

    Returns:
        str: time in seconds.
    """
    return str(int(time[:-1]) * SECONDS_PER_UNIT[time[-1]])


def expand_shorthand(short: str) -> list:
    """Expand shorthand naming notation.

    An example would be foo[1-3] = [foo1, foo2, foo3]

    Args:
        short (str): shorthand notation.

    Returns:
        array: expanded names.
    """

    match = re.match(r"(.+)\[(\d+)\-(\d+)\]", short)

    if match:
        expanded = []

        base = match.group(1)
        start = int(match.group(2))
        end = int(match.group(3)) + 1

        for i in range(start, end):
            expanded.append(f"{base}{i}")

        return expanded

    return [short]


def mm_send(mm: minimega.minimega, vm: str, src: str, dst: str) -> None:
    if not os.path.exists(src):
        raise ValueError(f"{src} not found locally")

    # Use PHENIX_DIR as base directory to ensure minimega has access to it. This
    # assumes PHENIX_DIR is mounted into the containers if containers are being
    # used.
    base = phenix_settings.PHENIX_DIR

    # If the well-known '/tmp/miniccc-mounts' directory is present, then use it
    # as the base directory instead. This is common when deploying minimega and
    # phenix as a Kubernetes deployment, wherein bidirectional mount propagation
    # has to be enabled (and is done so via a Kubernetes `emptyDir` volume).
    if Path("/tmp/miniccc-mounts").is_dir():
        base = "/tmp/miniccc-mounts"

    mm_cc_client_active(mm, vm)

    with tempfile.TemporaryDirectory(dir=base) as tmp:
        vm_dst = os.path.join(tmp, dst.strip("/"))
        dst_dir = os.path.dirname(vm_dst)

        try:
            mm.cc_mount(vm, tmp)
            time.sleep(1.0)

            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir, exist_ok=True)

            if os.path.isdir(src):
                shutil.copytree(src, vm_dst, dirs_exist_ok=True)
            else:
                shutil.copyfile(src, vm_dst)
        finally:
            mm.clear_cc_mount(vm)
            # race condition between miniccc clearing mount and temp directory being
            # cleaned up when exiting the context of the 'with' statement.
            time.sleep(1.0)


def mm_recv(mm: minimega.minimega, vm: str, src: list[str] | str, dst: str) -> None:
    """
    Transfer one or more files from a VM to a destination on the host using miniccc mounts.
    """

    # Use PHENIX_DIR as base directory to ensure minimega has access to it. This
    # assumes PHENIX_DIR is mounted into the containers if containers are being
    # used.
    base = phenix_settings.PHENIX_DIR

    # If the well-known '/tmp/miniccc-mounts' directory is present, then use it
    # as the base directory instead. This is common when deploying minimega and
    # phenix as a Kubernetes deployment, wherein bidirectional mount propagation
    # has to be enabled (and is done so via a Kubernetes `emptyDir` volume).
    if Path("/tmp/miniccc-mounts").is_dir():
        base = "/tmp/miniccc-mounts"

    mm_cc_client_active(mm, vm)

    with tempfile.TemporaryDirectory(dir=base) as tmp:
        if isinstance(src, str):
            src = [src]

        vm_sources = [os.path.join(tmp, s.strip("/")) for s in src]
        dst_dir = os.path.dirname(dst)

        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)

        try:
            mm.cc_mount(vm, tmp)

            for vm_src in vm_sources:
                tries = 0
                while not os.path.exists(vm_src):
                    tries += 1

                    if tries >= 5:
                        # finally block will still get called
                        raise ValueError(f"{src} not found in VM {vm}")
                    time.sleep(0.5)

                if os.path.isdir(vm_src):
                    shutil.copytree(vm_src, dst, dirs_exist_ok=True)
                else:
                    # shutil.copyfile(vm_src, dst)
                    shutil.copy2(vm_src, dst)  # file or dir destination
        finally:
            mm.clear_cc_mount(vm)
            # race condition between miniccc clearing mount and temp directory being
            # cleaned up when exiting the context of the 'with' statement.
            time.sleep(1.0)


def mm_get_cc_path(mm: minimega.minimega) -> Path | None:
    """
    Path: <MM_FILEPATH>/<EXPERIMENT-NAME>/miniccc_responses
    Example: /phenix/images/goes_scorch/miniccc_responses
    """
    if not mm._namespace:
        raise ValueError("no minimega namespace defined")

    cc_path = Path(phenix_settings.MM_FILEPATH, mm._namespace, "miniccc_responses")

    if not cc_path.is_dir():
        eprint(f"miniccc responses dir doesn't exist at {cc_path}")
        return None

    return cc_path


# seconds between cc client checks; matches Go util/mm c2ActiveCheckInterval
CC_POLL_RATE = float(os.environ.get("PHENIX_CC_POLL_RATE", 2.0))
# bounded window to ride out the gap between a response being counted and the
# exit code being recorded
CC_EXITCODE_GRACE = float(os.environ.get("PHENIX_CC_EXITCODE_GRACE", 10.0))
# bounded window for the miniccc client to register on a minimega host;
# matches Go util/mm DefaultC2Timeout
CC_CLIENT_GRACE = float(os.environ.get("PHENIX_CC_CLIENT_GRACE", 300.0))


def mm_cc_all_hosts(mm: minimega.minimega, method, *args) -> list:
    """Call an mm cc_* method and return ALL per-host response rows, without
    raising on an individual host's error.

    On a multi-host deployments, cc_exitcode / cc_responses fan out across the
    namespace: the host running the VM returns the data while sibling hosts
    report "no client <vm>" / "no responses for <id>". With raise_errors=True
    (the binding default) _get_response raises on the FIRST host error and
    discards the valid row, so we temporarily disable it and let the caller scan
    every row.
    """
    saved = mm._raise_errors
    mm._raise_errors = False

    try:
        return method(*args)
    finally:
        mm._raise_errors = saved


def mm_cc_client_active(
    mm: minimega.minimega,
    vm: str,
    grace: float = CC_CLIENT_GRACE,
    poll_rate: float = CC_POLL_RATE,
    by_uuid: bool = False,
) -> None:
    """Block until the miniccc client for ``vm`` is registered with minimega.

    Mirrors the Go util/mm IsC2ClientActive pre-flight. The miniccc agent
    can be transiently unresolvable which causes downstream cc_mount /
    cc_exec / cc_send calls to fail with "no such client: <uuid>". Polls
    ``cc client`` until a row matching ``vm`` appears on any host, or raises
    RuntimeError once ``grace`` is exceeded.

    By default ``vm`` is matched against the agent's self-reported hostname --
    this is intentionally strict so a VM that hasn't yet booted to the
    expected hostname (e.g. a Windows VM mid-rename) is not considered ready.
    Pass ``by_uuid=True`` to match by VM UUID instead.
    """
    column = "uuid" if by_uuid else "hostname"
    deadline = time.monotonic() + grace

    while True:
        responses = mm_cc_all_hosts(mm, mm.cc_clients)

        for resp in responses:
            header = resp.get("Header") or []
            tabular = resp.get("Tabular") or []

            if column not in header:
                continue

            col_idx = header.index(column)
            for row in tabular:
                if col_idx < len(row) and row[col_idx] == vm:
                    return

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out after {grace}s waiting for miniccc client on VM {vm}"
            )

        time.sleep(poll_rate)


def mm_cc_exitcode_wait(
    mm: minimega.minimega,
    cmd_id: str,
    client: str,
    grace: float = CC_EXITCODE_GRACE,
    poll_rate: float = CC_POLL_RATE,
) -> dict:
    """Wait for and return the cc exit-code response row for an already-completed
    command, tolerating multi-host fan-out.

    Only the host running the VM has the code; sibling hosts report
    "no client <vm>". Scan every host row and return the one carrying the code.
    ``grace`` bounds the wait for the gap between a response being counted and
    the exit code being recorded, raising RuntimeError if exceeded.
    """
    deadline = time.monotonic() + grace

    while True:
        rows = mm_cc_all_hosts(mm, mm.cc_exitcode, cmd_id, client)

        for row in rows:
            if not row.get("Error") and row.get("Response") not in (None, ""):
                return row

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out after {grace}s waiting for exit code of command "
                f"{cmd_id} on {client}"
            )

        logger.warning(
            f"exit code for {client} (cmd {cmd_id}) not yet reported by any host; "
            f"retrying"
        )
        time.sleep(poll_rate)


def mm_command_id(resp: list) -> str:
    """Return the id of the command just created by cc_exec / cc_exec_once /
    cc_send. minimega returns the new id in the response's ``Data`` field (see
    Namespace.NewCommand), so read it from the call that created the command
    rather than re-querying ``cc commands`` and guessing the last row -- the
    latter is racy when another component issues into the same namespace queue.

    The id is stringified to match the string id in ``cc commands`` tabular
    output (compared in mm_wait_for_cmd)."""
    for row in resp:
        if row.get("Data") is not None:
            return str(row["Data"])

    raise RuntimeError(f"no command id in cc response: {resp!r}")


def mm_exec_wait(
    mm: minimega.minimega,
    vm: str,
    cmd: str,
    once: bool = True,
    timeout: float = 0.0,
    poll_rate: float = 1.0,
    debug: bool = False,
) -> dict:
    mm_cc_client_active(mm, vm)
    mm.cc_filter(f"name={vm}")

    # Capture the new command's id directly from the cc_exec response rather than
    # re-querying cc commands afterward.
    resp = mm.cc_exec_once(cmd) if once else mm.cc_exec(cmd)
    cmd_id = mm_command_id(resp)

    mm_wait_for_cmd(
        mm=mm, cmd_id=cmd_id, timeout=timeout, poll_rate=poll_rate, debug=debug
    )

    # The command has completed (mm_wait_for_cmd saw a response). Fetch the exit
    # code by UUID; mm_cc_exitcode_wait scans all hosts and ignores the sibling
    # "no client" rows that the multi-host fan-out returns. Fall back to the VM
    # name if the UUID lookup comes back empty.
    uuid = mm_vm_uuid(mm, vm)
    grace = timeout if timeout else CC_EXITCODE_GRACE
    exit_resp = mm_cc_exitcode_wait(
        mm, cmd_id, uuid or vm, grace=grace, poll_rate=poll_rate
    )

    result = {
        "id": cmd_id,
        "cmd": cmd,
        "exitcode": int(exit_resp["Response"]),
        "stderr": None,
        "stdout": None,
    }

    # Read across all hosts: only the VM's host has the response; siblings report
    # "no responses" and would otherwise raise. The loop below already skips rows
    # with an empty Response.
    resps = mm_cc_all_hosts(mm, mm.cc_responses, cmd_id)

    # example response from mm.cc_responses:
    # [{
    #   'Host': 'kn-0',
    #   'Response': '1/0ab5dbc3-8ca6-4b75-a503-b5a191995dae/stdout:\nlo               UNKNOWN        127.0.0.1/8 ::1/128 \n\n',
    #   'Header': None,
    #   'Tabular': None,
    #   'Error': '',
    #   'Data': None
    # }]

    for row in resps:
        if not row["Response"]:
            continue

        resp = row["Response"]

        if uuid not in resp:
            eprint(f"UUID '{uuid}' not in response: {resp!r}")
            continue

        if "/stderr:\n" in resp:
            result["stderr"] = resp.partition("/stderr:\n")[2].strip()
        if "/stdout:\n" in resp:
            result["stdout"] = resp.partition("/stdout:\n")[2].strip()
        if "/stderr:\n" not in resp and "/stdout:\n" not in resp:
            eprint(f"no stderr or stdout in response: {resp!r}")

    return result


def mm_wait_for_cmd(
    mm: minimega.minimega,
    cmd_id: str,
    timeout: float = 0.0,
    poll_rate: float = 1.0,
    debug: bool = False,
) -> None:
    def last_test(c):
        return c[0] == cmd_id

    def done_test(c):
        return int(c[3]) > 0

    waiting = True
    counter = 0

    while waiting:
        # >>> mm.cc_commands()
        # [{'Host': 'harmonie', 'Response': '', 'Header': ['id', 'prefix', 'command', 'responses', 'background', 'once', 'sent', 'received', 'connectivity', 'level', 'filter'], 'Tabular': [['1', 'testing', '[/usr/bin/iperf3 --version]', '15', 'false', 'true', '[]', '[]', '', '', 'os=linux && iperf=1']], 'Error': '', 'Data': None}]
        commands = mm.cc_commands()

        for host in commands:
            last = list(filter(last_test, host["Tabular"]))
            done = list(filter(done_test, last))

            if len(done) > 0:
                waiting = False
                break

        if timeout and counter > int(timeout / poll_rate):
            raise RuntimeError(
                f"Timeout exceeded in mm_wait_for_command (timeout={timeout}, counter={counter}, poll_rate={poll_rate})"
            ) from None

        if debug:
            print_msg(
                f"Waiting {poll_rate} seconds before checking command for ID '{cmd_id}' in mm_wait_for_cmd (timeout={timeout}, counter={counter})"
            )

        time.sleep(poll_rate)
        counter += 1


def mm_wait_for_prefix(
    mm: minimega.minimega,
    prefix: str,
    num_responses: int,
    timeout: float = 0.0,
    poll_rate: float = 1.0,
    debug: bool = False,
) -> None:
    # 'Header': ['id', 'prefix', 'command', 'responses', 'background', 'once', 'sent', 'received', 'connectivity', 'level', 'filter']
    # 'Tabular': [['1', 'testing', '[/usr/bin/iperf3 --version]', '15', 'false', 'true', '[]', '[]', '', '', 'os=linux && iperf=1']]
    def last_test(c):
        return c[1] == prefix

    def done_test(c):
        return int(c[3]) == num_responses

    waiting = True
    counter = 0

    while waiting:
        commands = mm.cc_commands()

        for host in commands:
            last = list(filter(last_test, host["Tabular"]))
            done = list(filter(done_test, last))

            if len(done) > 0:
                waiting = False
                break

        if timeout and counter > int(timeout / poll_rate):
            raise RuntimeError(
                f"Timeout exceeded in mm_wait_for_prefix (timeout={timeout}, counter={counter}, poll_rate={poll_rate})"
            ) from None

        if debug:
            print_msg(
                f"Waiting {poll_rate} seconds before checking command for prefix '{prefix}' in mm_wait_for_prefix (timeout={timeout}, counter={counter})"
            )

        time.sleep(poll_rate)
        counter += 1


def mm_get_cc_responses(mm: minimega.minimega, id_or_prefix_or_all: str) -> list[dict]:
    # Read across all hosts so a sibling's "no responses" error doesn't abort the
    # call; the loop below skips rows with an empty Response.
    responses = mm_cc_all_hosts(mm, mm.cc_responses, id_or_prefix_or_all)
    results = []

    for row in responses:
        if not row["Response"]:
            continue

        cmd_resps = re.findall(
            r"(\d)/(\w+-\w+-\w+-\w+-\w+)/(.*?)/", row["Response"], re.DOTALL
        )

        for cmd_resp in cmd_resps:
            # ('1', '096b4042-9166-402c-895e-dd39fe0f83cd', 'stdout: ...')
            output = cmd_resp[2]
            cmd_result = {
                "id": cmd_resp[0],
                "uuid": cmd_resp[1],
                "all_output": output,
                "stderr": "",
                "stdout": "",
            }

            if "stderr:\n" in output:
                cmd_result["stderr"] = output.partition("stderr:\n")[2].strip()
            if "stdout:\n" in output:
                cmd_result["stdout"] = output.partition("stdout:\n")[2].strip()
            if "stderr:\n" not in output and "stdout:\n" not in output:
                print_msg(f"WARNING: no stderr or stdout in response: {output!r}")

            # Fetch the exit code by UUID, polling through transient multi-host
            # "no client" blips rather than a single blind retry.
            exit_resp = mm_cc_exitcode_wait(mm, cmd_result["id"], cmd_result["uuid"])
            cmd_result["exitcode"] = int(exit_resp["Response"])

            results.append(cmd_result)

    return results


def mm_last_command(mm: minimega.minimega) -> dict:
    """DEPRECATED -- do not use in new code.

    This infers "the command I just issued" as the last row of `cc commands`,
    which is racy: the cc-command queue is shared across every component in the
    namespace, so a concurrent (e.g. background) component can append a row
    between your cc_exec/cc_send and this call. Prefer reading the id directly
    from the cc call that created it: ``mm_command_id(mm.cc_send(...))`` /
    ``mm_command_id(mm.cc_exec_once(...))``. Retained only for backwards
    compatibility with out-of-tree callers.
    """
    warnings.warn(
        "mm_last_command should not be used. "
        "Use mm_command_id(mm.cc_send(...)) or mm_command_id(mm.cc_exec_once(...)) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    commands = mm.cc_commands()

    return {
        "id": commands[0]["Tabular"][-1][0],
        "cmd": mm.cc_commands()[0]["Tabular"][-1][2][1:-1],
    }


def mm_vm_uuid(mm: minimega.minimega, name: str) -> str | None:
    info = mm.vm_info(summary="summary")

    for host in info:
        for vm in host["Tabular"]:
            if vm[1] == name:
                return vm[4]

    return None


def mm_info_for_vm(mm: minimega.minimega, name: str) -> dict:
    return mm_vm_info(mm)["info"][name]


def mm_vm_info(mm: minimega.minimega) -> dict:
    """
    Returns information on VMs in the current minimega namespace.
    """
    responses = mm.vm_info()

    if len(responses) > 1:
        raise ValueError(
            f"Got {len(responses)} responses from 'mm vm info', expected 1 response"
        )

    # Headers: ['id', 'name', 'state', 'uptime', 'type', 'uuid', 'cc_active', 'pid', 'vlan', 'bridge', 'tap', 'mac', 'ip', 'ip6', 'qos', 'qinq', 'bond', 'memory', 'vcpus', 'disks', 'snapshot', 'initrd', 'kernel', 'cdrom', 'migrate', 'append', 'serial-ports', 'virtio-ports', 'vnc_port', 'usb-use-xhci', 'tpm-socket', 'filesystem', 'hostname', 'init', 'preinit', 'fifo', 'volume', 'console_port', 'tags']

    # Data keys, per item: ['UUID', 'VCPUs', 'Memory', 'Snapshot', 'Schedule', 'Colocate', 'Coschedule', 'Backchannel', 'Networks', 'Bonds', 'Tags', 'ID', 'Name', 'Namespace', 'Host', 'State', 'LaunchTime', 'Type', 'ActiveCC', 'Pid', 'QemuPath', 'KernelPath', 'InitrdPath', 'CdromPath', 'MigratePath', 'CPU', 'Sockets', 'Cores', 'Threads', 'Machine', 'SerialPorts', 'VirtioPorts', 'Vga', 'Append', 'Disks', 'UsbUseXHCI', 'TpmSocketPath', 'QemuAppend', 'QemuOverride', 'VNCPort']

    return {
        # Results from "mm vm info", keyed by VM name
        "info": {
            item[1]: dict(zip(responses[0]["Header"], item, strict=False))
            for item in responses[0]["Tabular"]
        },
        # Metadata about VMs, keyed by VM name
        "data": {data["Name"]: data for data in responses[0]["Data"]},
    }


def mm_kill_process(
    mm: minimega.minimega,
    cc_filter: str,
    process: str,
    os_type: str = "linux",
) -> None:
    mm.cc_filter(cc_filter)

    if os_type == "linux":
        mm.cc_exec_once(f"pkill {process}")
    elif os_type == "windows":
        # -f: forcefully kill
        # -im: image name to be terminated (iperf3.exe)
        mm.cc_exec_once(f"taskkill -f -im {process}")
    else:
        raise ValueError(
            f"unknown os_type '{os_type}' for mm_kill_process with filter '{cc_filter}'"
        )


def mm_delete_file(
    mm: minimega.minimega,
    cc_filter: str,
    filepath: str,
    os_type: str = "linux",
    glob_remove: bool = False,
) -> None:
    mm.cc_filter(cc_filter)

    if os_type == "linux":
        if glob_remove:
            if not filepath.endswith("*"):
                filepath += "*"
            # TODO: glob remove relative to arbitrary directory
            mm.cc_exec_once(
                f"bash -c '/usr/bin/find / -maxdepth 1 -wholename \"{filepath}\" -type f -print0 | /usr/bin/xargs -0 /bin/rm -f'"
            )
        else:
            mm.cc_exec_once(f"rm -f {filepath}")
    # TODO: this assumes file to delete is on C drive
    elif os_type == "windows":
        if filepath.startswith("/"):
            filepath = "c:" + filepath
        filepath = filepath.replace("/", "\\\\\\\\")

        # glob just works on windows
        if glob_remove and not filepath.endswith("*"):
            filepath += "*"

        mm.cc_exec_once(f"cmd /c del /q {filepath}")
    else:
        raise ValueError(
            f"unknown os_type '{os_type}' for mm_delete_file with filter '{cc_filter}'"
        )


def run_command(cmd: str, timeout: float | None = None) -> str:
    result = subprocess.check_output(cmd, shell=True, timeout=timeout)
    if isinstance(result, bytes):
        result = result.decode()
    return result


def read_json(path: str | Path):
    if isinstance(path, str):
        path = Path(path).resolve()

    with path.open(encoding="utf-8") as infile:
        return json.load(infile)


def write_json(
    path: str | Path, data: dict | list, indent: int | None = 4, sort: bool = False
) -> None:
    if isinstance(path, str):
        path = Path(path).resolve()

    if sort and isinstance(data, dict):
        data = sort_dict(data)  # sort by key before writing
    elif sort and isinstance(data, list):
        data = sorted(data)

    with path.open("w", encoding="utf-8", newline="\n") as outfile:
        json.dump(data, outfile, indent=indent)


def sort_dict(obj: dict) -> dict:
    return dict(sorted(obj.items(), key=lambda x: str(x[0])))


def copy_file(src_file: str | Path, dest_dir: str | Path) -> Path:
    """
    Copy file to the destination directory.
    """
    if isinstance(src_file, str):
        src_file = Path(src_file).expanduser().resolve()
    if isinstance(dest_dir, str):
        dest_dir = Path(dest_dir).expanduser().resolve()

    dest = Path(dest_dir, src_file.name).resolve()

    if not dest_dir.exists():
        dest_dir.mkdir(exist_ok=True, parents=True)

    return Path(shutil.copy2(str(src_file), str(dest))).resolve()


def rglob_copy(pattern: str, src_dir: Path, dest_dir: Path):
    """
    Copy any files matching the pattern in src_dir to dest_dir.
    """
    for path in src_dir.rglob(pattern):
        if path.is_file():
            copy_file(path, dest_dir)


def trim_pcap(
    pcap_path: Path, start_time: datetime.datetime, end_time: datetime.datetime
) -> None:
    """
    Edits a PCAP file to only contain packets between start_time and end_time.
    This replaces the input PCAP with the trimmed PCAP.

    This works with both .pcap and .pcapng format.
    """
    src = pcap_path.resolve()
    if not end_time > start_time:
        eprint(
            f"ERROR: end time '{end_time}' should be greater than start time '{start_time}' for pcap trim of {src}"
        )
        sys.exit(1)

    og_size = pcap_path.stat().st_size
    print_msg(f"Trimming PCAP {pcap_path.name} (size: {og_size} bytes)")

    edited = src.with_name(
        f"{src.stem}_edited{src.suffix}"
    )  # with_stem requires Python 3.9+
    cap_type = src.suffix.lstrip(".")  # pcap or pcapng

    # https://www.wireshark.org/docs/wsug_html_chunked/AppToolseditcap.html
    # YYYY-MM-DDThh:mm:ss.nnnnnnnnn[Z|+-hh:mm]
    # editcap -A start-time -B stop-time <infile> <outfile>
    run_command(
        f"editcap -F {cap_type} -A {start_time.isoformat()} -B {end_time.isoformat()} {src.as_posix()} {edited.as_posix()}"
    )

    trimmed_size = edited.stat().st_size

    # Don't modify file if sizes are the same
    if trimmed_size == og_size:
        print_msg(f"Trimmed size == source size for {src.name}, not overwriting")
        edited.unlink()
        return

    # switcharoo with original file to trimmed file
    src.unlink()
    edited.rename(src)

    print_msg(
        f"Trimmed size for {src.name}: {trimmed_size} bytes (reduced by {og_size - trimmed_size} bytes)"
    )


def pcap_capinfos(pcap_path: str | Path) -> dict:
    """
    Extract metadata from PCAP file. This also has the side effect of verifying that the PCAP file is valid.
    This will work with both PCAP (.pcap) and PCAPng (.pcapng) files.

    {'File name': './br14-0.pcap', 'File type': 'pcap', 'File encapsulation': 'ether', 'File time precision': 'microseconds', 'Packet size limit': '1600', 'Packet size limit min (inferred)': 'n/a', 'Packet size limit max (inferred)': 'n/a', 'Number of packets': '37', 'File size (bytes)': '3862', 'Data size (bytes)': '3246', 'Capture duration (seconds)': '28.975097', 'Start time': '2024-02-21 22:27:36.592584', 'End time': '2024-02-21 22:28:05.567681', 'Data byte rate (bytes/sec)': '112.03', 'Data bit rate (bits/sec)': '896.22', 'Average packet size (bytes)': '87.73', 'Average packet rate (packets/sec)': '1.28', 'SHA256': '2b07c65ec9f00c6ea3334ccd1f49074c4f643c68776a3a8cae990e824cbbf72a', 'SHA1': 'dcc7cb3f070b8757693a30a6e75ddc5542686072', 'Strict time order': 'True', 'Capture hardware': '', 'Capture oper-sys': '', 'Capture application': '', 'Capture comment': ''}
    """
    capinfo_output = run_command(f"capinfos -T -M {pcap_path}")

    io_obj = StringIO(capinfo_output)
    reader = csv.DictReader(io_obj, delimiter="\t")  # tab-delimited
    results = list(reader)
    io_obj.close()

    if len(results) > 1:
        raise ValueError(
            "More than one result from capinfos run! (this should never happen)"
        )

    return results[0]


def usec_to_sec(val: int | float) -> float:
    """
    Convert microseconds (usec) to seconds (sec).
    seconds = (usec * 1e-6)
    """
    return int(val) * 1e-6


def eprint(msg: str, ui: bool = True) -> None:
    """
    Prints errors to STDERR, and optionally flushed to STDOUT so it also
    gets streamed to the phenix UI.
    """

    print(msg, file=sys.stderr)

    if ui:
        tstamp = time.strftime("%H:%M:%S")
        print(f"[{tstamp}] ERROR : {msg}", flush=True)

    logger.error(msg)  # write error to phenix log file


def print_msg(msg: str, ts: bool = True) -> None:
    """
    Prints msg to STDOUT, flushing it immediately so it gets streamed to the
    phenix UI in a timely manner.
    """

    if ts:
        tstamp = time.strftime("%H:%M:%S")
        print(f"[{tstamp}] {msg}", flush=True)
    else:
        print(msg, flush=True)


# *** ELASTICSEARCH FUNCTIONS ***
def connect_elastic(server_url: str) -> Elasticsearch:
    es = Elasticsearch(server_url)

    # Check connection to Elasticsearch
    es_info = es.info()
    if not es_info:
        es.close()
        sys.exit(1)

    return es


def get_dated_index(base_index: str) -> str:
    # "rtds-clean" -> "rtds-clean-2022.07.18"
    # TODO: midnight issue, could query wrong data if close to midnight UTC
    return f"{base_index}-{utc_now().strftime('%Y.%m.%d')}"


def get_indices_from_range(
    base_index: str, start: datetime.datetime, stop: datetime.datetime
) -> str:
    # TODO: handle multiple dates between range
    assert start.day <= stop.day

    # rtds-clean-2022.07.18
    index_pat = f"{base_index}-{start.strftime('%Y.%m.%d')}"
    if start.day != stop.day:
        # rtds-clean-2022.07.18,rtds-clean-2022.07.19
        index_pat = f"{index_pat},{base_index}-{stop.strftime('%Y.%m.%d')}"

    return index_pat
