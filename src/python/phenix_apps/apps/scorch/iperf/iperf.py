import math
import re
from collections import Counter
from pathlib import Path, PurePath
from time import sleep
from typing import Annotated, Self

from box import Box
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
    Seconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


def _no_json_stream(value: str) -> str:
    # stop() reads each result file as one JSON document.
    if "--json-stream" in value:
        raise ValueError("--json-stream is not supported: results must be one document")
    return value


# Extra iperf arguments end up inside `bash -c '...'` after minimega has lexed the
# command (and turns a backslash-n into a newline), so only plain characters are
# allowed: no quotes, backslashes or shell syntax. An empty string is valid: it
# adds nothing, and on a client it suppresses the top-level arguments.
IperfArgs = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_ .,:=@%/+-]*$"),
    AfterValidator(_no_json_stream),
]

# Interface of a VM: an index into its interfaces, or an interface name.
IfaceRef = NonNegativeInt | Interface


def _version_matches(output: str, wanted: str, tool: str) -> bool:
    """Whether `--version` output reports `wanted`: exactly, or as the leading
    parts of a longer version (3.17 for 3.17.1), but not as part of a number
    (3.1 for 3.15)."""
    if found := re.search(rf"\b{tool} (\d+(?:\.\d+)*)", output):
        return found[1] == wanted or found[1].startswith(f"{wanted}.")
    return wanted in output


# Run on a Linux VM as a script file (see `_send_script`): minimega expands a
# bare `$name` in an inline cc command, which would mangle `$p` and `$n`. iperf3
# writes its own PID to the file given by --pidfile; the pid is used only while
# /proc shows an iperf process, so a stale file whose pid was reused is ignored.
def _pidfile_loop(process: str, action: str) -> str:
    return (
        'for f in /iperf_*.pid; do p=$(cat "$f" 2>/dev/null); '
        f'[ "$p" -gt 0 ] 2>/dev/null && grep -qa {process} "/proc/$p/cmdline" '
        f"&& {action}; done; true"
    )


class Client(MetadataBlock):
    hostname: Hostname
    interface: IfaceRef = 0
    add_server_args: IperfArgs | None = None
    add_client_args: IperfArgs | None = None
    bandwidth: PositiveInt | None = None


class Server(MetadataBlock):
    hostname: Hostname
    interface: IfaceRef = 0
    port_range_start: int = Field(ge=1, le=65535)
    clients: list[Client] = Field(min_length=1)


class IperfPaths(MetadataBlock):
    linux: FilePath | None = None
    windows: FilePath | None = None


class IperfMetadata(BaseModel):
    """Metadata for the iperf component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    # iperf3 caps --time and --idle-timeout (run_duration + 5) at 86400.
    run_duration: Annotated[PositiveSeconds, Field(le=86395)]
    iperf_paths: IperfPaths
    servers: list[Server] = Field(min_length=1)
    iperf_version: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    ) = None
    verify_execution: bool = True
    server_startup_delay: Seconds = 5.0
    use_rperf: bool = False
    create_histogram: bool = True
    collect_netstat_info: bool = False
    # Each client binds --cport to its server port plus this offset.
    client_port_offset: PositiveInt = 1000
    # Seconds `stop` waits for clients to finish, again if iperf3 is still
    # running, and after killing iperf.
    stop_grace: Seconds = 5.0
    add_server_args: IperfArgs | None = None
    add_client_args: IperfArgs | None = None
    bandwidth: PositiveInt | None = None

    @model_validator(mode="after")
    def _check_servers(self) -> Self:
        # The mapping is keyed by hostname, so a repeat would replace the
        # earlier entry.
        servers = [s.hostname for s in self.servers]
        if dupes := sorted({h for h in servers if servers.count(h) > 1}):
            raise ValueError(
                f"servers listed more than once: {', '.join(dupes)}; "
                "merge the entries' clients into one entry"
            )

        # Each client also gets the next port in its server's range.
        owner: dict[int, str] = {}
        for server in self.servers:
            clients = [c.hostname for c in server.clients]
            if dupes := sorted({h for h in clients if clients.count(h) > 1}):
                raise ValueError(
                    f"server {server.hostname}: clients listed more than once: "
                    f"{', '.join(dupes)}"
                )
            for i, client in enumerate(server.clients):
                port = server.port_range_start + i
                if port + self.client_port_offset > 65535:
                    raise ValueError(
                        f"server {server.hostname}: port {port} for client "
                        f"{client.hostname} is too high (its client port "
                        f"{port + self.client_port_offset} must be <= 65535)"
                    )
                if port in owner:
                    raise ValueError(
                        f"server {server.hostname}: port {port} for client "
                        f"{client.hostname} is already used by server {owner[port]}"
                    )
                owner[port] = server.hostname
        return self


class Iperf(ComponentBase):
    metadata_model = IperfMetadata
    config: IperfMetadata

    def __init__(self):
        ComponentBase.__init__(self, "iperf")
        self.execute_stage()

    def _get_node_info(self) -> dict:
        """
        minimega has no straightforward way to report a VM's OS, so read
        hardware.os_type from the topology. An unset os_type is linux, as
        phenix core defaults it.
        """
        vms = set()
        for server in self.config.servers:
            vms.add(server.hostname)
            for client in server.clients:
                vms.add(client.hostname)

        os_types = {}
        for vm in sorted(vms):
            os_type = self.extract_node_os_type(vm)
            if os_type not in ["linux", "windows"]:
                raise ValueError(
                    f'unknown os_type "{os_type}" for {vm} '
                    "(hardware.os_type must be linux or windows)"
                )
            if getattr(self.config.iperf_paths, os_type) is None:
                raise ValueError(
                    f"{vm} is {os_type}, but iperf_paths.{os_type} is not set"
                )
            os_types[vm] = os_type

        return {
            "vms": sorted(vms),
            "os_types": os_types,
            "os_count": Counter(os_types.values()),
        }

    @staticmethod
    def _process_names(mapping: Box, node_info: dict) -> dict[str, str]:
        """The executable name to look for on each OS, from the mapping."""
        names = {}
        for server in mapping.values():
            names[node_info["os_types"][server.hostname]] = server.process_name
            for client in server.clients.values():
                names[node_info["os_types"][client.hostname]] = client.process_name
        return names

    def _send_script(self, node_info: dict, name: str, body: str) -> str:
        """Send a script to every Linux VM by cc; return the command that runs it."""
        src = Path(self.root_dir) / self.exp_name / name
        src.write_text(body)
        try:
            for vm, os_type in node_info["os_types"].items():
                if os_type != "linux":
                    continue
                # a VM that is gone must not fail stop or cleanup for the rest;
                # running the script there then just fails
                try:
                    utils.mm_cc_send_wait(self.mm, vm, str(src), self.exp_name)
                except RuntimeError as e:
                    logger.warning(f"could not send {name} to VM {vm}: {e}")
        finally:
            self.mm.clear_cc_filter()
            src.unlink()
        return f"bash {PurePath('/tmp/miniccc/files') / self.exp_name / name}"

    def _kill_all_iperf(self, node_info: dict, mapping: Box) -> None:
        """kill iperf processes on all nodes."""
        logger.info(f"killing iperf on {len(node_info['vms'])} nodes")
        logger.info(f"nodes: {node_info['vms']}")

        names = self._process_names(mapping, node_info)
        for os_type, process in names.items():
            logger.info(f"killing {os_type} iperf processes")
            if self.config.use_rperf:
                # rperf has no PID file.
                # NOTE: pkill for a process not running on linux will have exit code of 1
                utils.mm_kill_process(
                    mm=self.mm,
                    cc_filter=f"iperf=1 os={os_type}",
                    process=process,
                    os_type=os_type,
                )
            elif os_type == "linux":
                # Only the processes this component started: iperf3 writes a PID
                # file for each (see start).
                run = self._send_script(
                    node_info, "iperf-kill.sh", _pidfile_loop(process, 'kill "$p"')
                )
                self.mm.cc_filter("iperf=1 os=linux")
                self.mm.cc_exec_once(run)
            else:
                # No PID file on Windows: a Cygwin build would write a Cygwin pid,
                # not a Windows one. miniccc keeps the processes it started, so
                # it kills those by their command text (every command has
                # `--logfile /iperf_...`), never another iperf3.exe.
                self.mm.cc_filter("iperf=1 os=windows")
                self.mm.cc_process_killall("/iperf_")

        self.mm.clear_cc_filter()
        sleep(2.0)

    def _iperf_running(self, node_info: dict, mapping: Box) -> bool:
        """Whether iperf is still running on any VM."""
        for os_type, process in self._process_names(mapping, node_info).items():
            count = node_info["os_count"][os_type]
            if os_type == "linux":
                script = f"n=0; {_pidfile_loop(process, 'n=$((n+1))')}; echo running=$n"
                responses = self._run_multi(
                    cmd=self._send_script(node_info, "iperf-running.sh", script),
                    cc_filter="iperf=1 os=linux",
                    prefix="iperf_running_linux",
                    num_responses=count,
                    timeout=15.0,
                )
                if any(
                    int(m[1])
                    for r in responses
                    if (m := re.search(r"running=(\d+)", r["stdout"]))
                ):
                    return True
            else:
                responses = self._run_multi(
                    cmd="tasklist",
                    cc_filter="iperf=1 os=windows",
                    prefix="iperf_running_windows",
                    num_responses=count,
                    timeout=15.0,
                )
                if any(process.lower() in r["stdout"].lower() for r in responses):
                    return True
        return False

    def _delete_all_iperf(self, node_info: dict):
        """delete iperf JSON data files for clients and servers."""
        logger.info(f"removing iperf3 JSON files on {len(node_info['vms'])} nodes")

        # farm deletion command to all tagged VMs
        for os_type in ["linux", "windows"]:
            if node_info["os_count"].get(os_type):
                logger.info(f"deleting {os_type} iperf files")
                utils.mm_delete_file(
                    mm=self.mm,
                    cc_filter=f"iperf=1 os={os_type}",
                    filepath="/iperf_*",
                    os_type=os_type,
                    glob_remove=True,
                )

        self.mm.clear_cc_filter()
        sleep(2.0)

    def _interface(self, hostname: str, interface: int | str):
        """The node and the topology interface selected by an index or name."""
        _, index = self.get_host_and_iface(
            Box({"hostname": hostname, "interface": interface})
        )
        node = self.require_node(hostname)
        if index >= len(node.network.interfaces):
            raise ValueError(
                f"interface {index} does not exist on node {hostname} "
                f"(it has {len(node.network.interfaces)})"
            )
        return node, node.network.interfaces[index]

    def _build_iperf_mapping(self) -> Box:
        mapping = {}
        all_ports = set()
        logger.info("building iperf mapping")

        for server in self.config.servers:
            _, s_if = self._interface(server.hostname, server.interface)
            s_exe = Path(
                getattr(
                    self.config.iperf_paths, self.extract_node_os_type(server.hostname)
                )
            )
            s_map = {
                **server.model_dump(exclude_unset=True),
                "ip": s_if.address,
                "interface": s_if.name,
                "exe_path": str(s_exe),
                "process_name": s_exe.name,
                "clients": {},
            }

            curr_port = server.port_range_start

            for client in server.clients:
                _, c_if = self._interface(client.hostname, client.interface)

                if curr_port in all_ports:
                    raise ValueError(
                        f"port {curr_port} is already defined! something is funky.\nclient: {client}\nserver: {server}"
                    )
                all_ports.add(curr_port)

                c_exe = Path(
                    getattr(
                        self.config.iperf_paths,
                        self.extract_node_os_type(client.hostname),
                    )
                )
                c_map = {
                    **client.model_dump(exclude_unset=True),
                    # a client's own setting wins over the top-level one, even an
                    # empty add_*_args, which switches the inherited ones off
                    **{
                        name: (
                            getattr(self.config, name)
                            if getattr(client, name) is None
                            else getattr(client, name)
                        )
                        for name in ("add_server_args", "add_client_args", "bandwidth")
                    },
                    "port": curr_port,
                    "ip": c_if.address,
                    "interface": c_if.name,
                    "exe_path": str(c_exe),
                    "process_name": c_exe.name,
                    "server_log_path": f"/iperf_server-data_client-{client.hostname}_server-{server.hostname}.json",
                    "client_log_path": f"/iperf_client-data_client-{client.hostname}_server-{server.hostname}.json",
                    "server_pid_path": f"/iperf_server-pid_client-{client.hostname}_server-{server.hostname}.pid",
                    "client_pid_path": f"/iperf_client-pid_client-{client.hostname}_server-{server.hostname}.pid",
                }

                s_map["clients"][client.hostname] = c_map
                curr_port += 1

            mapping[server.hostname] = s_map

        return Box(mapping)

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")
        node_info = self._get_node_info()

        # Generate iperf mapping and save it to a JSON file
        mapping = self._build_iperf_mapping()
        mapping_path = self.base_dir / "iperf_mapping.json"
        logger.info(f"Saving iperf mapping to {mapping_path}")
        utils.write_json(mapping_path, mapping)

        # Apply a tag to all VMs that will have iperf run on them.
        # This will be used to leverage miniccc filters to execute
        # commands in parallel across all VMs.
        logger.info(f"applying tag 'iperf=1' to {len(node_info['vms'])} VMs")
        for vm in node_info["vms"]:
            self.mm.vm_tag(vm, "iperf", "1")

        # only check if loops aren't defined or it's the first iteration of a loop
        if not self.config.verify_execution:
            logger.info(
                "skipping iperf execution and version checks since verify_execution=false"
            )
        elif self.count > 1:
            logger.info(
                f"skipping iperf execution and version checks since count {self.count} > 1"
            )
        else:
            iperf_ver = self.config.iperf_version

            for os_type in ["linux", "windows"]:
                if node_info["os_count"].get(os_type):
                    logger.info(
                        f"verifying iperf execution and version for {node_info['os_count'][os_type]} {os_type} VMs"
                    )

                    # /usr/bin/iperf3 --version
                    exe_path = getattr(self.config.iperf_paths, os_type)

                    responses = self._run_multi(
                        cmd=f"{exe_path} --version",
                        cc_filter=f"iperf=1 os={os_type}",
                        prefix=f"iperf_version_{os_type}",
                        num_responses=node_info["os_count"][os_type],
                    )

                    for response in responses:
                        stdout = response["stdout"]
                        vm = f"VM {response.get('uuid', '?')}"

                        if not self.config.use_rperf and "iperf" not in stdout:
                            raise RuntimeError(
                                f"iperf not in output for {vm} (path={exe_path})\nresponse: {response}"
                            )

                        if iperf_ver is not None:
                            tool = "rperf" if self.config.use_rperf else "iperf"
                            if not _version_matches(stdout, iperf_ver, tool):
                                raise RuntimeError(
                                    f"incorrect iperf version for {vm}, expected {iperf_ver} (path={exe_path})\nresponse: {response}"
                                )

        # Ensure there are no lingering processes or files from previous runs
        self.mm.clear_cc_prefix()
        self._kill_all_iperf(node_info, mapping)
        self._delete_all_iperf(node_info)
        self.mm.clear_cc_prefix()
        self.mm.clear_cc_commands()
        self.mm.clear_cc_responses()

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")
        node_info = self._get_node_info()
        mapping = self._build_iperf_mapping()

        logger.info(
            f"starting iperf3 for {len(node_info['vms'])} VMs with {len(self.config.servers)} iperf servers"
        )

        # Start iperf server processes
        logger.info("Starting iperf server processes...")
        for server in mapping.values():
            utils.mm_cc_filter_vm(self.mm, server.hostname)  # e.g. "control-scada"

            # Only need 1 server process for rperf
            if self.config.use_rperf:
                server_cmd = f"{server.exe_path} --server"
                # TODO: add_server_args from metadata for rperf
                logger.info(f"server_cmd for '{server.hostname}': {server_cmd}")
                self.mm.cc_background(server_cmd)
            else:
                # Start a server process for each client it will be communicating with
                for client in server.clients.values():
                    logger.info(
                        f"starting iperf server process for client '{client.hostname}' on server '{server.hostname}'"
                    )

                    idle_timeout = math.ceil(self.config.run_duration + 5.0)
                    server_cmd = f"{server.exe_path} --server --one-off --bind {server.ip} --json --logfile {client.server_log_path} --port {client.port} --idle-timeout {idle_timeout}"

                    is_linux = node_info["os_types"][server.hostname] == "linux"
                    if is_linux:
                        server_cmd += f" --pidfile {client.server_pid_path}"

                    # Add user-configured arguments to the iperf server process for this client
                    if client.add_server_args:
                        server_cmd += f" {client.add_server_args}"

                    # debugging logs
                    if is_linux:
                        server_cmd = f"bash -c '{server_cmd} >/iperf_server-log_client-{client.hostname}_server-{server.hostname}.log 2>&1'"

                    logger.info(f"server_cmd for {server.hostname}: {server_cmd}")
                    retval = self.mm.cc_background(server_cmd)
                    logger.info(
                        f"return val from 'cc background' for server_cmd: {retval}"
                    )

        self.mm.clear_cc_filter()

        # Wait for server processes to start user-configurable delay
        startup_delay = self.config.server_startup_delay
        logger.info(
            f"Waiting {startup_delay} seconds for iperf server processes to start..."
        )
        sleep(startup_delay)

        # TODO: generate a bash script that handles client processes
        #   ensures no processes are running
        #   ensures files are deleted
        #   starts client and logs to file

        # Start client processes
        # iperf3 man page: https://software.es.net/iperf/invoking.html#iperf3-manual-page
        logger.info("Starting iperf client processes")
        for server in mapping.values():
            for client in server.clients.values():
                logger.info(
                    f"starting iperf client process on {client.hostname} (client={client.hostname}, server={server.hostname})"
                )
                run_for = self.config.run_duration

                if self.config.use_rperf:
                    client_cmd = (
                        f"{client.exe_path} --client {server.ip} --time {run_for}"
                    )

                    # Add bandwidth argument
                    if client.bandwidth is not None:
                        client_cmd += f" --bandwidth {client.bandwidth}"
                    # TODO: add_client_args from metadata for rperf
                else:
                    # "--client" with the IP of the server is slightly confusing here.
                    # Basically, our client (this device) is connecting to a iperf server,
                    # which is this device's client.
                    # NOTE: don't use UDP, won't get rtt
                    client_cmd = f"{client.exe_path} --client {server.ip} --json --port {client.port} --logfile {client.client_log_path} --bind {client.ip} --time {math.ceil(run_for)} --cport {client.port + self.config.client_port_offset}"

                    is_linux = node_info["os_types"][client.hostname] == "linux"
                    if is_linux:
                        client_cmd += f" --pidfile {client.client_pid_path}"

                    # Add bandwidth argument
                    if client.bandwidth is not None:
                        client_cmd += f" --bitrate {client.bandwidth}"

                    # Add additional arguments to the client process
                    if client.add_client_args:
                        client_cmd += f" {client.add_client_args}"

                    # debugging logs (Windows has no bash)
                    if is_linux:
                        client_cmd = f"bash -c '{client_cmd} >/iperf_client-log_client-{client.hostname}_server-{server.hostname}.log 2>&1'"

                logger.info(f"client_cmd for '{client.hostname}': {client_cmd}")
                utils.mm_cc_filter_vm(self.mm, client.hostname)
                self.mm.cc_background(client_cmd)

        logger.info("finished starting all iperf processes")
        logger.info(f"Started user component: {self.name}")

    def _run_multi(
        self,
        cmd: str,
        cc_filter: str,
        prefix: str,
        num_responses: int,
        timeout: float = 10.0,
    ) -> list:
        self.mm.clear_cc_prefix()
        self.mm.cc_filter(cc_filter)
        self.mm.cc_prefix(prefix)
        self.mm.cc_exec_once(cmd)

        # wait for responses count to reach count of VMs of the type
        utils.mm_wait_for_prefix(
            self.mm, prefix, num_responses=num_responses, timeout=timeout
        )
        responses = utils.mm_get_cc_responses(self.mm, prefix)

        for response in responses:
            if not response["stdout"] or response.get("exitcode") != 0:
                raise RuntimeError(
                    f"failed to execute command '{cmd}' with filter '{cc_filter}'\nresponse: {response}"
                )
        self.mm.clear_cc_prefix()

        return responses

    def _get_netstat_info(self, node_info: dict) -> None:
        # the smarter way to do this would be to cc_filter, write to a file, then retrieve and consolidate the files
        logger.info("getting netstat info")

        nix_ns_res = self._run_multi(
            cmd="netstat -tulanp",
            cc_filter="iperf=1 os=linux",
            prefix="netstat_linux",
            num_responses=node_info["os_count"]["linux"],
        )

        nix_ss_res = self._run_multi(
            cmd="ss -tulp4",
            cc_filter="iperf=1 os=linux",
            prefix="ss_linux",
            num_responses=node_info["os_count"]["linux"],
        )

        win_ns_res = self._run_multi(
            cmd="netstat -ano",
            cc_filter="iperf=1 os=windows",
            prefix="netstat_windows",
            num_responses=node_info["os_count"]["windows"],
        )

        # self.mm.clear_cc_prefix()
        # self.mm.cc_filter(f"iperf=1 os=linux")
        # self.mm.cc_prefix("netstat_linux")
        # self.mm.cc_exec_once("netstat -tulanp")

        # ns_outputs = ""
        # ss_outputs = ""
        # for vm in node_info["vms"]:
        #     if node_info["os_types"][vm] == "linux":
        #         ns_res = self.run_and_check_command(vm, "netstat -tulanp")["stdout"]
        #         ss_res = self.run_and_check_command(vm, "ss -tulp4")["stdout"]
        #         ns_outputs += f"** {vm} **\n{ns_res}\n\n"
        #         ss_outputs += f"** {vm} **\n{ss_res}\n\n"
        #     elif node_info["os_types"][vm] == "windows":
        #         ns_res = self.run_and_check_command(vm, "netstat -ano", timeout=10)["stdout"]

        ns_outputs = ""
        ss_outputs = ""

        for ns_res in nix_ns_res:
            ns_outputs += f"\n{ns_res['stdout']}\n\n"

        for ns_res in win_ns_res:
            ns_outputs += f"\n{ns_res['stdout']}\n\n"

        for ss_res in nix_ss_res:
            ss_outputs += f"\n{ss_res['stdout']}\n\n"

        logger.info("saving netstat info to files")
        (self.base_dir / "netstat_outputs.txt").write_text(ns_outputs)
        (self.base_dir / "ss_outputs.txt").write_text(ss_outputs)

    def _collect_files(self, mapping: Box, node_info: dict) -> None:
        # One transfer per VM with all of its files, not one per file.
        sources: dict[str, list[str]] = {}
        for server in mapping.values():
            for client in server.clients.values():
                pair = f"client-{client.hostname}_server-{server.hostname}"
                sources.setdefault(client.hostname, []).append(client.client_log_path)
                sources.setdefault(server.hostname, []).append(client.server_log_path)

                # debugging logs, only written on Linux (see start)
                if node_info["os_types"][client.hostname] == "linux":
                    sources[client.hostname].append(f"/iperf_client-log_{pair}.log")
                if node_info["os_types"][server.hostname] == "linux":
                    sources[server.hostname].append(f"/iperf_server-log_{pair}.log")

        for vm, files in sources.items():
            logger.info(f"collecting {len(files)} iperf files from '{vm}'")
            utils.mm_recv(mm=self.mm, vm=vm, src=files, dst=str(self.base_dir))

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")
        node_info = self._get_node_info()
        mapping = self._build_iperf_mapping()

        if not self.config.use_rperf:
            sleep(self.config.stop_grace)
            # !!! WARNING: terminating iperf client early will cause JSON results to NOT be saved OR result in error flag being set !!!
            if self._iperf_running(node_info, mapping):
                logger.info(
                    f"iperf is still running, sleeping for {self.config.stop_grace} seconds to give it time to quit..."
                )
                sleep(self.config.stop_grace)

        if self.config.collect_netstat_info:
            try:
                self._get_netstat_info(node_info)
            except Exception as ex:
                logger.error(f"WARNING: failed to get netstat data for iperf: {ex}")

        self._kill_all_iperf(node_info, mapping)

        if not self.config.use_rperf:
            sleep(self.config.stop_grace)

        # collect results
        if not self.config.use_rperf:
            logger.info(f"collecting iperf results for {len(node_info['vms'])} nodes")

            self._collect_files(mapping, node_info)

            # verify error field isn't set in iperf results
            for file in self.base_dir.glob("*.json"):
                try:
                    data = utils.read_json(file)
                except Exception as ex:
                    raise RuntimeError(
                        f"failed to read iperf data from '{file}': {ex}"
                    ) from ex

                if data.get("error"):
                    raise RuntimeError(
                        f"error field set for iperf data from '{file}': {data['error']}"
                    )

            # Generate RTT histograms
            # TODO: generate histograms using matplotlib
            if self.config.create_histogram:
                logger.info("generating RTT histograms (create_histogram=true)")
                for server in mapping.values():
                    for client in server.clients.values():
                        logger.info(
                            f"generating RTT histogram for client '{client.hostname}' and server '{server.hostname}'"
                        )
                        c_path = (
                            self.base_dir / PurePath(client["client_log_path"]).name
                        )
                        results = utils.read_json(c_path)  # type: dict

                        # get number of intervals using jq:
                        # cat iperf_client-data_client-br14_server-control-scada.json | jq '.intervals | length'
                        rtt_times = []
                        for interval in results["intervals"]:
                            rtt_times.append(
                                utils.usec_to_sec(interval["streams"][0]["rtt"])
                            )

                        # RTT text file contents, one value per line
                        # Limit the float precision to 6
                        hist_str = (
                            "\n".join(f"{t:.06f}" for t in rtt_times) + "\n"
                        )  # add final newline

                        # "iperf_server-data_client-load5_server-load8.json" => "load5_load8"
                        pair_name = (
                            c_path.name.replace(".json", "")
                            .split("-data_")[-1]
                            .replace("client-", "")
                            .replace("server-", "")
                            .replace("_", "-")
                        )

                        rtt_hist_file = self.base_dir / f"rtt_histogram_{pair_name}.txt"
                        logger.info(
                            f"Writing RTT histogram to {rtt_hist_file} (client={client.hostname}, server={server.hostname})"
                        )
                        rtt_hist_file.write_text(hist_str, encoding="utf-8")
        else:
            logger.info("using rperf, skipping data collection and processing")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")
        node_info = self._get_node_info()

        self.mm.clear_cc_prefix()

        if not self.config.use_rperf:
            self._delete_all_iperf(node_info)

        for vm in node_info["vms"]:
            self.mm.clear_vm_tag(vm, "iperf")

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Iperf()


if __name__ == "__main__":
    main()
