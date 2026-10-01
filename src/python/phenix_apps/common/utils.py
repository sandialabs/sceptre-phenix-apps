import csv
import datetime
import json
import math
import random
import re
import shutil
import socket
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
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger


def utc_now() -> datetime.datetime:
    """
    This simple helper function ensures a proper UTC-aware timestamp is returned.

    Further reading: https://blog.miguelgrinberg.com/post/it-s-time-for-a-change-datetime-utcnow-is-now-deprecated
    """
    return datetime.datetime.now(datetime.UTC)


def kibana_format_time(ts: datetime.datetime) -> str:
    return ts.strftime("%b %d, %Y @ %H:%M:%S.%f").replace(".000000", ".000")


# minimega's wildcard VM target, and the name phenix's Windows startup
# wrapper and built images use.
RESERVED_HOSTNAMES = frozenset({"all", "phenix"})


def validate_hostname(name: str) -> str:
    """
    Validate a hostname against phenix core's node-name rules as of v2026.10.02:
    2 to 63 letters, digits and interior hyphens, not all digits, and not a
    reserved name.
    """
    if (
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]", name)
        or name.isdigit()
        or name.lower() in RESERVED_HOSTNAMES
    ):
        raise AppError(f"invalid hostname '{name}'")

    return name


def safe_join(base: str | Path, *parts: str | Path) -> Path:
    """
    Join base with parts and ensure the resolved result stays within the
    resolved base directory (rejects '..' traversal and absolute components).

    This is the canonical pathlib containment idiom for this codebase: all
    guest-controlled relative parts must be joined through here.
    """
    resolved_base = Path(base).resolve()
    joined = resolved_base.joinpath(*parts).resolve()

    if joined != resolved_base and not joined.is_relative_to(resolved_base):
        raise AppError(f"path '{joined}' escapes base directory '{resolved_base}'")

    return joined


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
    path = Path(file_path)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


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


def abs_path(file_: str, relative_path: str | None = None) -> Path:
    """Return absolute path to file_ with optional relative resource.

    Args:
        file_ (str): Name of file.
        relative_path (str): Optional relative path of resource.

    Returns:
        Path: Full path to file_ (and optional relative resource).
    """

    base_path = Path(file_).parent.absolute()
    return base_path / relative_path if relative_path else base_path


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


# `cc commands` columns, in order (minimega cmd/minimega/cc_cli.go)
CC_CMD_COLUMNS = (
    "id",
    "prefix",
    "command",
    "responses",
    "background",
    "once",
    "sent",
    "received",
    "connectivity",
    "level",
    "filter",
)


def _cc_cmd_field(row: list, column: str) -> str | None:
    """Value of ``column`` in a ``cc commands`` row, or None if truncated."""
    idx = CC_CMD_COLUMNS.index(column)

    return row[idx] if idx < len(row) else None


class _WaitLog:
    """Rate-limit a poll loop's "still waiting" line, backing off as the wait grows."""

    def __init__(
        self,
        interval: float = phenix_settings.CC_LOG_INTERVAL,
        max_interval: float = phenix_settings.CC_LOG_MAX_INTERVAL,
    ) -> None:
        self.interval = interval
        self.max_interval = max_interval
        self._due = time.monotonic() + interval

    def due(self) -> bool:
        """True at most once per interval; advances to the next one."""
        if time.monotonic() < self._due:
            return False

        self.interval = min(self.interval * 2, self.max_interval)
        self._due = time.monotonic() + self.interval

        return True


def mm_send(
    mm: minimega.minimega,
    vm: str,
    src: str,
    dst: str,
    grace: float = phenix_settings.CC_CLIENT_GRACE,
) -> None:
    if not Path(src).exists():
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

    mm_cc_client_active(mm, vm, grace=grace)

    with tempfile.TemporaryDirectory(dir=base) as tmp:
        vm_dst = safe_join(tmp, dst.strip("/"))
        dst_dir = vm_dst.parent

        try:
            mm.cc_mount(vm, tmp)
            time.sleep(1.0)

            if not dst_dir.exists():
                dst_dir.mkdir(parents=True, exist_ok=True)

            if Path(src).is_dir():
                shutil.copytree(src, vm_dst, dirs_exist_ok=True)
            else:
                shutil.copyfile(src, vm_dst)
        finally:
            mm.clear_cc_mount(vm)
            # race condition between miniccc clearing mount and temp directory being
            # cleaned up when exiting the context of the 'with' statement.
            time.sleep(1.0)


def mm_recv(
    mm: minimega.minimega,
    vm: str,
    src: list[str] | str,
    dst: str,
    grace: float = phenix_settings.CC_CLIENT_GRACE,
) -> None:
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

    # PurePath construction collapses spurious slashes and single-dot segments
    # (but not '..'), so str(Path(dst)) == dst is equivalent to the old
    # os.path.normpath(dst) == dst normalization check.
    if not Path(dst).is_absolute() or str(Path(dst)) != dst or ".." in Path(dst).parts:
        raise AppError(
            f"invalid host destination path '{dst}' (must be absolute and normalized, with no '..' segments)"
        )

    mm_cc_client_active(mm, vm, grace=grace)

    with tempfile.TemporaryDirectory(dir=base) as tmp:
        if isinstance(src, str):
            src = [src]

        vm_sources = [safe_join(tmp, s.strip("/")) for s in src]
        dst_dir = Path(dst).parent

        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)

        try:
            mm.cc_mount(vm, tmp)

            for vm_src in vm_sources:
                tries = 0
                while not vm_src.exists():
                    tries += 1

                    if tries >= 5:
                        # finally block will still get called
                        raise ValueError(f"{src} not found in VM {vm}")
                    time.sleep(0.5)

                if vm_src.is_dir():
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


def mm_cc_all_hosts(mm: minimega.minimega, method, *args, **kwargs) -> list:
    """Call an mm method and return every per-host response row, without raising
    on one host's error.
    """
    saved = mm._raise_errors
    mm._raise_errors = False

    try:
        return method(*args, **kwargs)
    finally:
        mm._raise_errors = saved


def mm_cc_client_seen(mm: minimega.minimega, uuid: str) -> str | None:
    """Minimega host reporting ``uuid`` in ``cc clients``, or None.

    A single miss is a sample, not proof -- miniccc heartbeats every ~5s.
    """
    for resp in mm_cc_all_hosts(mm, mm.cc_clients):
        header = resp.get("Header") or []

        if "uuid" not in header:
            continue

        idx = header.index("uuid")

        for row in resp.get("Tabular") or []:
            if idx < len(row) and row[idx].lower() == uuid.lower():
                return resp.get("Host")

    return None


def mm_cc_client_locate(
    mm: minimega.minimega,
    vm: str,
    grace: float = phenix_settings.CC_CLIENT_GRACE,
    poll_rate: float = phenix_settings.CC_POLL_RATE,
    by_uuid: bool = False,
) -> tuple[str, str]:
    """Block until the miniccc client for ``vm`` registers; return its
    ``(uuid, host)``.

    ``host`` is the minimega host that owns the client -- cc command ids are
    per-host, so id lookups must be aimed at it. ``by_uuid=True`` allows ``vm``
    to already be a UUID.
    """
    start = time.monotonic()
    deadline = start + grace
    wait_log = _WaitLog()
    uuid = None

    while True:
        # Retried, not resolved once: one miss is a sample, not proof.
        if uuid is None:
            uuid = mm_vm_uuid(mm, vm)

        candidate = uuid or (vm if by_uuid else None)

        if candidate is not None:
            host = mm_cc_client_seen(mm, candidate)

            if host is not None:
                return candidate, host

        if time.monotonic() >= deadline:
            if candidate is None:
                raise RuntimeError(f"vm {vm} does not exist in the namespace")

            raise RuntimeError(
                f"timed out after {grace}s waiting for miniccc client on VM "
                f"{vm} (uuid {candidate})"
            )

        if wait_log.due():
            logger.warning(
                f"miniccc client for VM {vm} (uuid {candidate}) not yet registered "
                f"after {time.monotonic() - start:.1f}s (grace {grace}s); retrying"
            )

        time.sleep(poll_rate)


def mm_cc_filter_vm(
    mm: minimega.minimega, vm: str, grace: float = phenix_settings.CC_CLIENT_GRACE
) -> tuple[str, str]:
    """Point the cc filter at ``vm`` by UUID; return its ``(uuid, host)``.

    By UUID, not name: ``name`` is not a cc filter field, so ``cc filter
    name=`` matches on tags and silently targets zero clients.
    """
    uuid, host = mm_cc_client_locate(mm, vm, grace=grace)
    mm.cc_filter(f"uuid={uuid}")

    return uuid, host


def mm_cc_send_wait(
    mm: minimega.minimega,
    vm: str,
    src: str,
    exp_name: str,
    grace: float = phenix_settings.CC_SEND_GRACE,
) -> None:
    """Send file ``src`` to ``vm`` via cc and wait for it to land.

    The filename identifies the invocation, so the ``sent`` column is matched
    too.
    """
    uuid, host = mm_cc_filter_vm(mm, vm)
    cmd_id = mm_command_id_for_host(mm.cc_send(src), host)

    mm_wait_for_cmd(
        mm,
        cmd_id,
        timeout=grace,
        client=uuid,
        host=host,
        match_column="sent",
        match_value=f"[{exp_name}/{Path(src).name}]",
    )


def mm_cc_client_active(
    mm: minimega.minimega,
    vm: str,
    grace: float = phenix_settings.CC_CLIENT_GRACE,
    poll_rate: float = phenix_settings.CC_POLL_RATE,
    by_uuid: bool = False,
) -> str:
    """DEPRECATED -- use :func:`mm_cc_client_locate`, which also returns the
    minimega host owning the client."""
    warnings.warn(
        "mm_cc_client_active does not return the host owning the client. "
        "Use mm_cc_client_locate instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    uuid, _ = mm_cc_client_locate(
        mm, vm, grace=grace, poll_rate=poll_rate, by_uuid=by_uuid
    )

    return uuid


def mm_cc_exitcode_wait(
    mm: minimega.minimega,
    cmd_id: str,
    client: str,
    grace: float = phenix_settings.CC_EXITCODE_GRACE,
    poll_rate: float = phenix_settings.CC_POLL_RATE,
    host: str | None = None,
) -> dict:
    """Wait for and return the cc exit-code row for a completed command.

    Only the host running the VM has the code; siblings report "no client". Pass
    ``host`` to scope the lookup -- cc ids are per-host. minimega's own errors
    are folded into the timeout message.
    """
    if host is None:
        logger.warning(
            f"mm_cc_exitcode_wait called without a host for cmd {cmd_id}; cc ids "
            "are per-host, so this may read a sibling host's unrelated command"
        )

    deadline = time.monotonic() + grace
    wait_log = _WaitLog()
    errors = []

    while True:
        rows = mm_cc_all_hosts(mm, mm.cc_exitcode, cmd_id, client)

        errors = [row["Error"] for row in rows if row.get("Error")]

        for row in rows:
            if host is not None and row.get("Host") != host:
                continue

            if not row.get("Error") and row.get("Response") not in (None, ""):
                return row

        detail = f"; last errors from minimega: {'; '.join(errors)}" if errors else ""

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out after {grace}s waiting for exit code of command "
                f"{cmd_id} on {client}{detail}"
            )

        if wait_log.due():
            logger.warning(
                f"exit code for {client} (cmd {cmd_id}) not yet reported by any "
                f"host; retrying{detail}"
            )

        time.sleep(poll_rate)


def mm_command_ids(resp: list) -> dict[str, str]:
    """Map each minimega host to the id it gave the command just created.

    ``cc`` is broadcast and every host numbers the command from its own counter,
    so there is no namespace-global id. Read from the creating call's ``Data``
    field.
    """
    ids = {
        row["Host"]: str(row["Data"])
        for row in resp
        if row.get("Data") is not None and row.get("Host")
    }

    if not ids:
        raise RuntimeError(f"no command id in cc response: {resp!r}")

    return ids


def mm_command_id(resp: list) -> str:
    """DEPRECATED -- use :func:`mm_command_id_for_host`; cc command ids are
    per-host."""
    warnings.warn(
        "mm_command_id assumes a namespace-global cc command id, but ids are "
        "per-host. Use mm_command_id_for_host instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    for row in resp:
        if row.get("Data") is not None:
            return str(row["Data"])

    raise RuntimeError(f"no command id in cc response: {resp!r}")


def mm_command_id_for_host(resp: list, host: str) -> str:
    """The id ``host`` assigned to the command just created. Missing means the
    command went elsewhere."""
    ids = mm_command_ids(resp)
    cmd_id = ids.get(host)

    if cmd_id is None:
        raise RuntimeError(
            f"host {host} owns the target client but never created its own copy "
            f"of the command; only {sorted(ids)} did"
        )

    return cmd_id


def mm_exec_wait(
    mm: minimega.minimega,
    vm: str,
    cmd: str,
    once: bool = True,
    timeout: float = phenix_settings.CC_CMD_GRACE,
    poll_rate: float = 1.0,
    debug: bool = False,
    client_grace: float = phenix_settings.CC_CLIENT_GRACE,
) -> dict:
    """Run ``cmd`` on ``vm`` via cc and wait for it to finish.

    ``timeout`` bounds the response wait; 0 (the default) waits indefinitely,
    supervised instead by the client staying registered.
    """
    uuid, host = mm_cc_filter_vm(mm, vm, grace=client_grace)

    resp = mm.cc_exec_once(cmd) if once else mm.cc_exec(cmd)
    cmd_id = mm_command_id_for_host(resp, host)

    mm_wait_for_cmd(
        mm=mm,
        cmd_id=cmd_id,
        timeout=timeout,
        poll_rate=poll_rate,
        debug=debug,
        client=uuid,
        client_grace=client_grace,
        host=host,
        # No content match: minimega re-renders the command as argv, so it will
        # not compare equal.
    )

    exit_resp = mm_cc_exitcode_wait(
        mm,
        cmd_id,
        uuid or vm,
        grace=phenix_settings.CC_EXITCODE_GRACE,
        poll_rate=poll_rate,
        host=host,
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
    timeout: float = phenix_settings.CC_CMD_GRACE,
    poll_rate: float = 1.0,
    debug: bool = False,
    client: str | None = None,
    client_grace: float = phenix_settings.CC_CLIENT_GRACE,
    host: str | None = None,
    match_column: str | None = None,
    match_value: str | None = None,
    appear_grace: float = phenix_settings.CC_SEND_GRACE,
) -> None:
    """Block until cc command ``cmd_id`` has at least one response.

    The row must appear on ``host`` within ``appear_grace``, then ``timeout``
    (0 = unbounded) bounds the response wait, supervised by ``client`` staying
    in ``cc clients``. ``match_column``/``match_value`` additionally require the
    row's content to be ours.
    """
    start = time.monotonic()
    deadline = start + timeout
    appear_deadline = start + appear_grace
    wait_log = _WaitLog()
    last_seen = start
    next_check = start + phenix_settings.CC_LIVENESS_INTERVAL
    seen = host is None

    while True:
        # >>> mm.cc_commands()
        # 'Header': ['id', 'prefix', 'command', 'responses', 'background', 'once', 'sent', 'received', 'connectivity', 'level', 'filter']
        # 'Tabular': [['1', 'testing', '[/usr/bin/iperf3 --version]', '15', 'false', 'true', '[]', '[]', '', '', 'os=linux && iperf=1']]
        for resp in mm_cc_all_hosts(mm, mm.cc_commands):
            if host is not None and resp.get("Host") != host:
                continue

            for row in resp.get("Tabular") or []:
                if not row or row[0] != cmd_id:
                    continue

                # Same id, different payload: not ours.
                if (
                    match_value is not None
                    and _cc_cmd_field(row, match_column) != match_value
                ):
                    continue

                seen = True

                if int(_cc_cmd_field(row, "responses") or 0) > 0:
                    return

        now = time.monotonic()
        elapsed = now - start

        if not seen and now >= appear_deadline:
            raise RuntimeError(
                f"cc command {cmd_id} never appeared on host {host} within "
                f"{appear_grace}s; it was most likely created under a different "
                "namespace"
            ) from None

        if timeout and now >= deadline:
            raise RuntimeError(
                f"timed out after {elapsed:.1f}s waiting for cc command "
                f"{cmd_id} (timeout={timeout})"
            ) from None

        if client and now >= next_check:
            next_check = now + phenix_settings.CC_LIVENESS_INTERVAL

            if mm_cc_client_seen(mm, client) is not None:
                last_seen = now
            elif now - last_seen > client_grace:
                raise RuntimeError(
                    f"miniccc client {client} unreachable for "
                    f"{now - last_seen:.1f}s while waiting for cc command {cmd_id}"
                )

        if wait_log.due():
            logger.info(
                f"waiting for cc command {cmd_id} on {host} (elapsed={elapsed:.1f}s, "
                f"client={client}, timeout={timeout})"
            )

        if debug:
            print_msg(
                f"Waiting {poll_rate} seconds before checking command for ID "
                f"'{cmd_id}' in mm_wait_for_cmd (timeout={timeout}, "
                f"elapsed={elapsed:.1f})"
            )

        time.sleep(poll_rate)


def mm_wait_for_prefix(
    mm: minimega.minimega,
    prefix: str,
    num_responses: int,
    timeout: float = phenix_settings.CC_SEND_GRACE,
    poll_rate: float = 1.0,
    debug: bool = False,
) -> None:
    """Block until ``num_responses`` responses have arrived on all hosts for
    commands matching the prefix."""
    start = time.monotonic()
    deadline = start + timeout
    wait_log = _WaitLog()

    while True:
        # 'Header': ['id', 'prefix', 'command', 'responses', 'background', 'once', 'sent', 'received', 'connectivity', 'level', 'filter']
        # 'Tabular': [['1', 'testing', '[/usr/bin/iperf3 --version]', '15', 'false', 'true', '[]', '[]', '', '', 'os=linux && iperf=1']]
        seen = 0

        for resp in mm_cc_all_hosts(mm, mm.cc_commands):
            for row in resp.get("Tabular") or []:
                if _cc_cmd_field(row, "prefix") != prefix:
                    continue

                seen += int(_cc_cmd_field(row, "responses") or 0)

        if seen >= num_responses:
            return

        now = time.monotonic()
        elapsed = now - start

        if timeout and now >= deadline:
            raise RuntimeError(
                f"timed out after {elapsed:.1f}s waiting for {num_responses} cc "
                f"responses with prefix '{prefix}' (timeout={timeout})"
            ) from None

        if wait_log.due():
            logger.info(
                f"waiting for cc commands with prefix '{prefix}' "
                f"(elapsed={elapsed:.1f}s, timeout={timeout})"
            )

        if debug:
            print_msg(
                f"Waiting {poll_rate} seconds before checking command for prefix "
                f"'{prefix}' in mm_wait_for_prefix (timeout={timeout}, "
                f"elapsed={elapsed:.1f})"
            )

        time.sleep(poll_rate)


def mm_get_cc_responses(mm: minimega.minimega, id_or_prefix_or_all: str) -> list[dict]:
    # Read across all hosts so a sibling's "no responses" error doesn't abort the
    # call; the loop below skips rows with an empty Response.
    responses = mm_cc_all_hosts(mm, mm.cc_responses, id_or_prefix_or_all)
    results = []

    for row in responses:
        if not row["Response"]:
            continue

        # \d+, not \d: a single digit truncates ids >= 10.
        cmd_resps = re.findall(
            r"(\d+)/(\w+-\w+-\w+-\w+-\w+)/(.*?)/", row["Response"], re.DOTALL
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

            # The id came from this host's response, so scope the lookup to it.
            exit_resp = mm_cc_exitcode_wait(
                mm, cmd_result["id"], cmd_result["uuid"], host=row.get("Host")
            )
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
    """UUID of VM ``name``, or None. Exact match -- minimega preserves the
    launched case."""
    for host in mm_cc_all_hosts(mm, mm.vm_info, summary="summary"):
        header = host.get("Header") or []

        if "name" not in header or "uuid" not in header:
            continue

        name_idx, uuid_idx = header.index("name"), header.index("uuid")

        for vm in host.get("Tabular") or []:
            if max(name_idx, uuid_idx) < len(vm) and vm[name_idx] == name:
                return vm[uuid_idx]

    return None


def mm_info_for_vm(mm: minimega.minimega, name: str) -> dict:
    return mm_vm_info(mm)["info"][name]


def mm_vm_info(mm: minimega.minimega) -> dict:
    """
    Returns information on VMs in the current minimega namespace.
    """
    # One response per host on a mesh, each with only its own VMs -- merge them.
    responses = mm_cc_all_hosts(mm, mm.vm_info)

    info: dict = {}
    data: dict = {}

    for resp in responses:
        if resp.get("Error"):
            continue

        header = resp.get("Header") or []

        for item in resp.get("Tabular") or []:
            info[item[header.index("name")]] = dict(zip(header, item, strict=False))

        for entry in resp.get("Data") or []:
            data[entry["Name"]] = entry

    # Headers: ['id', 'name', 'state', 'uptime', 'type', 'uuid', 'cc_active', 'pid', 'vlan', 'bridge', 'tap', 'mac', 'ip', 'ip6', 'qos', 'qinq', 'bond', 'memory', 'vcpus', 'disks', 'snapshot', 'initrd', 'kernel', 'cdrom', 'migrate', 'append', 'serial-ports', 'virtio-ports', 'vnc_port', 'usb-use-xhci', 'tpm-socket', 'filesystem', 'hostname', 'init', 'preinit', 'fifo', 'volume', 'console_port', 'tags']

    # Data keys, per item: ['UUID', 'VCPUs', 'Memory', 'Snapshot', 'Schedule', 'Colocate', 'Coschedule', 'Backchannel', 'Networks', 'Bonds', 'Tags', 'ID', 'Name', 'Namespace', 'Host', 'State', 'LaunchTime', 'Type', 'ActiveCC', 'Pid', 'QemuPath', 'KernelPath', 'InitrdPath', 'CdromPath', 'MigratePath', 'CPU', 'Sockets', 'Cores', 'Threads', 'Machine', 'SerialPorts', 'VirtioPorts', 'Vga', 'Append', 'Disks', 'UsbUseXHCI', 'TpmSocketPath', 'QemuAppend', 'QemuOverride', 'VNCPort']

    return {
        # Results from "mm vm info", keyed by VM name
        "info": info,
        # Metadata about VMs, keyed by VM name
        "data": data,
    }


def _mm_init(namespace: str | None = None) -> minimega.minimega:
    """
    The minimega.connect function will print a message to STDOUT if there is
    a version mismatch. This utility function prevents that from happening.
    """

    saved_stdout = sys.stdout

    sys.stdout = open("/dev/null", "w")

    mm = None

    if namespace:
        mm = minimega.connect(path=phenix_settings.MM_SOCKET_PATH, namespace=namespace)
    else:
        mm = minimega.connect(path=phenix_settings.MM_SOCKET_PATH)

    sys.stdout.close()
    sys.stdout = saved_stdout

    return mm


def mm_compute_cmd(mm: minimega.minimega, **kwargs) -> list[dict]:
    """Send command to compute nodes using minimega API.

    Args:
        mm: minimega connection object
        **kwargs: Arbitrary keyword arguments including:
            experiment: Experiment name/namespace
            computes: Comma-separated list of compute nodes or 'all'
            command: Command to execute
            command_type: Type of command (default: 'shell')
            ignore_error: Whether to ignore errors (default: False)

    Returns:
        List of response dictionaries from minimega

    Raises:
        ValueError: If required parameters are missing
        RuntimeError: If command fails and ignore_error is False
    """
    # Validate required parameters
    required_params = ["experiment", "computes", "command"]
    for param in required_params:
        if param not in kwargs:
            raise ValueError(f"Missing required parameter: {param}")

    experiment = kwargs["experiment"]
    computes = kwargs.get("computes", "all")  # 'all' or comma-separated list
    computes_list = computes.split(",")
    command = kwargs["command"]
    command_type = kwargs.get("command_type", "shell")
    ignore_error = kwargs.get("ignore_error", False)

    # Save current namespace and switch to experiment namespace
    original_namespace = mm._namespace
    mm.namespace(experiment)

    results = []

    try:
        hostname = socket.gethostname().split("-")[0]
        if len(computes_list) == 1 and hostname in computes_list[0]:
            cmd = f"namespace {experiment} {command_type} {command}"
        else:
            cmd = (
                f"namespace {experiment} mesh send {computes} {command_type} {command}"
            )
        logger.debug(cmd)
        results = _mm_socket_cmd(cmd, ignore_error=ignore_error)

    except Exception as e:
        if not ignore_error:
            raise RuntimeError(f"Command failed: {e}") from e
        logger.warning(f"Command failed (ignored): {e}")
    finally:
        # Restore original namespace
        if original_namespace:
            mm.namespace(original_namespace)

    return results


def _mm_socket_cmd(cmd: str, ignore_error: bool = False) -> list[str]:
    """Send command to minimega socket and get a response.

    Args:
        cmd (string): Command to run.

    Returns:
        list: List of JSON data elements in the minimega response.
    """
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(phenix_settings.MM_SOCKET_PATH)
    socketfile = client.makefile("rb")

    msg = json.dumps({"Command": f"{cmd}"})
    if len(msg) != client.send(msg.encode("utf-8")):
        logger.error("_socket_cmd(): Failed to write message to minimega")
        client.close()
        sys.exit(1)
    response = _mm_get_response(socketfile)
    if response["Resp"] and response["Resp"][0]["Error"] and not ignore_error:
        err = response["Resp"][0]["Error"]
        logger.error(f"_socket_cmd(): Command: '{cmd}' -- Response: '{err}'")
        client.close()
        sys.exit(1)
    client.close()
    return response["Resp"]


def _mm_get_response(socketfile: IO) -> dict:
    """
    _get_response reads a single response from minimega
    """
    line = socketfile.readline().decode("utf-8")
    response = json.loads(line)
    if not response:
        logger.error("_socket_cmd(): Expected response, socket closed")
        sys.exit(1)
    return response


def mm_host_info(mm: minimega.minimega) -> list[dict]:
    """Get host information using minimega API.

    This function provides compatibility with the internal phenix.services.minimega
    API by adapting the minimega Python package.

    Args:
        mm: minimega connection object

    Returns:
        List of dictionaries containing host information, each with at least:
        - 'name': Host name
        - Other host metadata from minimega

    Raises:
        RuntimeError: If unable to get host information
    """
    try:
        # Get host information from minimega
        host_data = mm.host()
        hosts = []
        for host_item in host_data:
            if not host_item.get("Tabular"):
                continue

            header = host_item["Header"]

            for row in host_item["Tabular"]:
                host_info = dict(zip(header, row, strict=False))

                # Convert data types as needed (similar to internal implementation)
                for key, value in host_info.items():
                    if key in ["tx", "rx"] and isinstance(value, str):
                        try:
                            host_info[key] = float(value)
                        except ValueError:
                            pass
                    elif key == "load" and isinstance(value, str):
                        try:
                            host_info[key] = [float(val) for val in value.split()]
                        except ValueError:
                            pass
                    elif (
                        key not in ["name", "uptime"]
                        and isinstance(value, str)
                        and value.isdigit()
                    ):
                        try:
                            host_info[key] = int(value)
                        except ValueError:
                            pass

                # Fix uptime format using existing utility
                if "uptime" in host_info:
                    host_info["uptime"] = hms_to_timedelta(host_info["uptime"])

                # Add hostname
                host_info["name"] = host_item["Host"]

                hosts.append(host_info)

        return hosts

    except Exception as e:
        raise RuntimeError(f"Failed to get host information: {e}") from e


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
