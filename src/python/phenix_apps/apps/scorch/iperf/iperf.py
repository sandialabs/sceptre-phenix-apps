import sys
import os.path
from collections import Counter
from pathlib import Path
from time import sleep

from box import Box

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils

# TODO: configure which interface to use
# OR be smart and determine which interface to use based on subnets
# TODO: this doesn't allow servers that are on multiple VLANs
# e.g. more than 2 interfaces

# TODO: rename component to "netperf" or something like that

class Iperf(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'iperf')
        self.execute_stage()

    def _get_node_info(self) -> dict:
        """
        There doesn't seem to be a straightforward way to get OS
        information from minimega. Inspecting the topology
        (self.experiment.spec.topology) would usually work
        using "hardware.os_type", however it COULD fail if
        someone neglected to include os_type for a node.
        """
        vms = set()
        for server in self.metadata.servers:
            vms.add(server.hostname)
            for client in server.clients:
                vms.add(client.hostname)

        os_types = {}
        for node in self.experiment.spec.topology.nodes:
            if node.general.hostname in vms:
                os_type = node.hardware.os_type.lower()
                if os_type not in ["linux", "windows"]:
                    self.eprint(f'unknown os_type "{os_type}" for {node.general.hostname}')
                    sys.exit(1)
                os_types[node.general.hostname] = os_type

        node_info = {
            "vms": sorted(list(vms)),
            "os_types": os_types,
            "os_count": Counter(os_types.values()),
        }

        return node_info

    def _kill_all_iperf(self, node_info: dict) -> None:
        """kill iperf3 processes on all nodes."""
        self.print(f"killing iperf3 on {len(node_info['vms'])} nodes")
        self.print(f"nodes: {node_info['vms']}")

        # TODO: use iperf mapping
        # use filename of exe for process to kill
        win_proc = Path(self.metadata.iperf_paths.windows).name  # iperf3.exe, rperf.exe
        linux_proc = Path(self.metadata.iperf_paths.linux).name  # iperf3, rperf

        for os_type in ["linux", "windows"]:
            if node_info["os_count"].get(os_type):
                self.print(f"killing {os_type} iperf processes")
                # NOTE: pkill for a process not running on linux will have exit code of 1
                utils.mm_kill_process(
                    mm=self.mm,
                    cc_filter=f"iperf=1 os={os_type}",
                    # process="iperf3" if os_type=="linux" else "iperf3.exe",
                    process=linux_proc if os_type=="linux" else win_proc,
                    os_type=os_type
                )

        self.mm.clear_cc_filter()
        sleep(2.0)

    def _delete_all_iperf(self, node_info: dict):
        """delete iperf JSON data files for clients and servers."""
        self.print(f"removing iperf3 JSON files on {len(node_info['vms'])} nodes")

        # farm deletion command to all tagged VMs
        for os_type in ["linux", "windows"]:
            if node_info["os_count"].get(os_type):
                self.print(f"deleting {os_type} iperf files")
                utils.mm_delete_file(
                    mm=self.mm,
                    cc_filter=f"iperf=1 os={os_type}",
                    filepath="/iperf_*",
                    os_type=os_type,
                    glob_remove=True,
                )

        self.mm.clear_cc_filter()
        sleep(2.0)

    def _build_iperf_mapping(self) -> Box:
        mapping = {}
        all_ports = set()
        self.print("building iperf mapping")

        for server in self.metadata.servers:
            s_node = self.extract_node(server.hostname)
            s_if = s_node.network.interfaces[0]  # TODO: be smarter about selecting interface
            s_exe = Path(self.metadata.iperf_paths[s_node.hardware.os_type.lower()])
            s_map = {
                **server,
                "ip": s_if.address,
                "interface": s_if.name,
                "exe_path": str(s_exe),
                "process_name": s_exe.name,
                "clients": {},
            }

            curr_port = server.port_range_start  # type: int

            for client in server.clients:
                c_node = self.extract_node(client.hostname)
                c_if = c_node.network.interfaces[0]  # TODO: be smarter about selecting interface

                if curr_port in all_ports:
                    self.eprint(f"port {curr_port} is already defined! something is funky.\nclient: {client}\nserver: {server}")
                    sys.exit(1)
                all_ports.add(curr_port)

                c_exe = Path(self.metadata.iperf_paths[c_node.hardware.os_type.lower()])
                c_map = {
                    **client,
                    "port": curr_port,
                    "ip": c_if.address,
                    "interface": c_if.name,
                    "exe_path": str(c_exe),
                    "process_name": c_exe.name,
                    "server_log_path": f"/iperf_server-data_client-{client.hostname}_server-{server.hostname}.json",
                    "client_log_path": f"/iperf_client-data_client-{client.hostname}_server-{server.hostname}.json",
                }

                s_map["clients"][client.hostname] = c_map
                curr_port += 1

            mapping[server.hostname] = s_map

        return Box(mapping)

    def _get_setting(self, name: str, obj: Box):
        if obj.get(name) is not None:
            return obj[name]
        elif self.metadata.get(name) is not None:
            return self.metadata[name]  # type: ignore
        return None

    def configure(self):
        logger.log('INFO', f'Configuring user component: {self.name}')
        node_info = self._get_node_info()

        # Generate iperf mapping and save it to a JSON file
        mapping = self._build_iperf_mapping()
        mapping_path = Path(self.base_dir, "iperf_mapping.json")
        self.print(f"Saving iperf mapping to {mapping_path}")
        utils.write_json(mapping_path, mapping)

        # Apply a tag to all VMs that will have iperf run on them.
        # This will be used to leverage miniccc filters to execute
        # commands in parallel across all VMs.
        self.print(f"applying tag 'iperf=1' to {len(node_info['vms'])} VMs")
        for vm in node_info["vms"]:
            self.mm.vm_tag(vm, "iperf", "1")

        # only check if loops aren't defined or it's the first iteration of a loop
        if not bool(self.metadata.get("verify_execution", True)):
            self.print("skipping iperf execution and version checks since verify_execution=false")
        elif self.count > 1:
            self.print(f"skipping iperf execution and version checks since count {self.count} > 1")
        else:
            iperf_ver = self.metadata.get("iperf_version")  # type: str

            for os_type in ["linux", "windows"]:
                if node_info["os_count"].get(os_type):
                    self.print(f"verifying verifying iperf execution and version for {node_info['os_count'][os_type]} {os_type} VMs")

                    # /usr/bin/iperf3 --version
                    exe_path = self.metadata.iperf_paths[os_type]

                    responses = self._run_multi(
                        cmd=f"{exe_path} --version",
                        filter=f"iperf=1 os={os_type}",
                        prefix=f"iperf_version_{os_type}",
                        num_responses=node_info["os_count"][os_type],
                    )

                    for response in responses:
                        stdout = response["stdout"]

                        if not self.metadata.get("use_rperf") and "iperf" not in stdout:
                            self.eprint(f"iperf not in output for {vm} (path={exe_path})\nresponse: {response}")
                            sys.exit(1)

                        if iperf_ver is not None:
                            if self.metadata.get("use_rperf"):
                                check_for = f"rperf {iperf_ver}"
                            else:
                                check_for = f"iperf {iperf_ver}"
                            if check_for not in stdout and iperf_ver not in stdout:
                                self.eprint(f"incorrect iperf version for {vm}, expected {iperf_ver} (path={exe_path})\nresponse: {response}")
                                sys.exit(1)

        # Ensure there are no lingering processes or files from previous runs
        self.mm.clear_cc_prefix()
        self._kill_all_iperf(node_info)
        self._delete_all_iperf(node_info)
        self.mm.clear_cc_prefix()
        self.mm.clear_cc_commands()
        self.mm.clear_cc_responses()

        logger.log('INFO', f'Configured user component: {self.name}')

    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')
        node_info = self._get_node_info()
        mapping = self._build_iperf_mapping()

        self.print(f"starting iperf3 for {len(node_info['vms'])} VMs with {len(self.metadata.servers)} iperf servers")

        # Start iperf server processes
        self.print("Starting iperf server processes...")
        for server in mapping.values():
            self.mm.cc_filter(f"name={server.hostname}")  # e.g. "control-scada"

            # Only need 1 server process for rperf
            if self.metadata.get("use_rperf"):
                server_cmd = f"{server.exe_path} --server"
                # TODO: add_server_args from metadata for rperf
                self.print(f"server_cmd for '{server.hostname}': {server_cmd}")
                self.mm.cc_background(server_cmd)
            else:
                # Start a server process for each client it will be communicating with
                for client in server.clients.values():
                    self.print(f"starting iperf server process for client '{client.hostname}' on server '{server.hostname}'")

                    idle_timeout = float(self.metadata.run_duration) + 5.0
                    server_cmd = f"{server.exe_path} --server --one-off --bind {server.ip} --json --port {client.port} --logfile {client.server_log_path} --idle-timeout {idle_timeout}"

                    # Add user-configured arguments to the iperf server process for this client
                    add_server_args = self._get_setting("add_server_args", client)
                    if add_server_args is not None:
                        server_cmd += f" {add_server_args.strip()}"

                    # debugging logs
                    if node_info["os_types"][server.hostname] == "linux":
                        server_cmd = f"bash -c '{server_cmd} 2>1 >/iperf_server-log_client-{client.hostname}_server-{server.hostname}.log'"

                    self.print(f"server_cmd for {server.hostname}: {server_cmd}")
                    retval = self.mm.cc_background(server_cmd)
                    self.print(f"return val from 'cc background' for server_cmd: {retval}")

        self.mm.clear_cc_filter()

        # Wait for server processes to start user-configurable delay
        startup_delay = float(self.metadata.get("server_startup_delay", 5.0))
        self.print(f"Waiting {startup_delay} seconds for iperf server processes to start...")
        sleep(startup_delay)

        # TODO: generate a bash script that handles client processes
        #   ensures no processes are running
        #   ensures files are deleted
        #   starts client and logs to file

        # Start client processes
        # iperf3 man page: https://software.es.net/iperf/invoking.html#iperf3-manual-page
        self.print("Starting iperf client processes")
        for server in mapping.values():
            for client in server.clients.values():
                self.print(f"starting iperf client process on {client.hostname} (client={client.hostname}, server={server.hostname})")
                run_for = float(self.metadata.run_duration)

                if self.metadata.get("use_rperf"):
                    client_cmd = f"{client.exe_path} --client {server.ip} --time {run_for}"

                    # Add bandwidth argument
                    bandwidth = self._get_setting("bandwidth", client)
                    if bandwidth is not None:
                        client_cmd += f" --bandwidth {int(bandwidth)}"
                    # TODO: add_client_args from metadata for rperf
                else:
                    # "--client" with the IP of the server is slightly confusing here.
                    # Basically, our client (this device) is connecting to a iperf server,
                    # which is this device's client.
                    # NOTE: don't use UDP, won't get rtt
                    client_cmd = f"{client.exe_path} --client {server.ip} --json --port {client.port} --logfile {client.client_log_path} --bind {client.ip} --time {run_for} --cport {client.port+1000}"

                    # Add bandwidth argument
                    bandwidth = self._get_setting("bandwidth", client)
                    if bandwidth is not None:
                        client_cmd += f" --bitrate {int(bandwidth)}"

                    # Add additional arguments to the client process
                    add_client_args = self._get_setting("add_client_args", client)
                    if add_client_args is not None:
                        client_cmd += f" {add_client_args.strip()}"

                    # debugging logs
                    client_cmd = f"bash -c '{client_cmd} 2>1 >/iperf_client-log_client-{client.hostname}_server-{server.hostname}.log'"

                self.print(f"client_cmd for '{client.hostname}': {client_cmd}")
                self.mm.cc_filter(f"name={client.hostname}")
                self.mm.cc_background(client_cmd)

        self.print("finished starting all iperf processes")
        logger.log('INFO', f'Started user component: {self.name}')

    def _run_multi(self, cmd: str, filter: str, prefix: str, num_responses: int, timeout: float = 10.0) -> list:
        self.mm.clear_cc_prefix()
        self.mm.cc_filter(filter)
        self.mm.cc_prefix(prefix)
        self.mm.cc_exec_once(cmd)

        # wait for responses count to reach count of VMs of the type
        utils.mm_wait_for_prefix(self.mm, prefix, num_responses=num_responses, timeout=timeout)
        responses = utils.mm_get_cc_responses(self.mm, prefix)

        for response in responses:
            if not response["stdout"] or response.get("exitcode") != 0:
                self.eprint(f"failed to execute command '{cmd}' with filter '{filter}'\nresponse: {response}")
                sys.exit(1)
        self.mm.clear_cc_prefix()

        return responses

    def _get_netstat_info(self, node_info: dict) -> None:
        # the smarter way to do this would be to cc_filter, write to a file, then retrieve and consolidate the files
        self.print("getting netstat info")

        nix_ns_res = self._run_multi(
            cmd="netstat -tulanp",
            filter="iperf=1 os=linux",
            prefix="netstat_linux",
            num_responses=node_info["os_count"]["linux"],
        )

        nix_ss_res = self._run_multi(
            cmd="ss -tulp4",
            filter="iperf=1 os=linux",
            prefix="ss_linux",
            num_responses=node_info["os_count"]["linux"],
        )

        win_ns_res = self._run_multi(
            cmd="netstat -ano",
            filter="iperf=1 os=windows",
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

        self.print("saving netstat info to files")
        Path(self.base_dir, "netstat_outputs.txt").write_text(ns_outputs)
        Path(self.base_dir, "ss_outputs.txt").write_text(ss_outputs)

    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')
        node_info = self._get_node_info()
        mapping = self._build_iperf_mapping()

        if not self.metadata.get("use_rperf"):
            sleep(5.0)
            # !!! WARNING: terminating iperf client early will cause JSON results to NOT be saved OR result in error flag being set !!!
            if self.check_process_running(node_info["vms"][0], "iperf3", node_info["os_types"][node_info["vms"][0]]):
                self.print(f"iperf is still running on {node_info['vms'][0]}, sleeping for 5 seconds to give it time to quit...")
                sleep(5.0)

        if self.metadata.get("collect_netstat_info", False):
            try:
                self._get_netstat_info(node_info)
            except Exception as ex:
                self.eprint(f"WARNING: failed to get netstat data for iperf: {ex}")

        self._kill_all_iperf(node_info)

        if not self.metadata.get("use_rperf"):
            sleep(5.0)

        # collect results
        # TODO: parallelize file collection using miniccc filters?
        if not self.metadata.get("use_rperf"):
            self.print(f"collecting iperf results for {len(node_info['vms'])} nodes")
            for server in mapping.values():
                for client in server.clients.values():
                    # client results (this has the more interesting data)
                    self.print(f"collecting iperf client data from '{client.hostname}'")
                    utils.mm_recv(
                        mm=self.mm,
                        vm=client.hostname,
                        src=client["client_log_path"],
                        dst=os.path.join(self.base_dir, os.path.basename(client["client_log_path"])),
                    )

                    # server results for this client
                    self.print(f"collecting iperf server data for client '{client.hostname}' from server '{server.hostname}'")
                    utils.mm_recv(
                        mm=self.mm,
                        vm=server.hostname,
                        src=client["server_log_path"],
                        dst=os.path.join(self.base_dir, os.path.basename(client["server_log_path"])),
                    )

                    # debugging logs
                    utils.mm_recv(
                        mm=self.mm,
                        vm=client.hostname,
                        src=f"/iperf_client-log_client-{client.hostname}_server-{server.hostname}.log",
                        dst=os.path.join(self.base_dir, f"iperf_client-log_client-{client.hostname}_server-{server.hostname}.log"),
                    )
                    if node_info["os_types"][server.hostname] == "linux":
                        utils.mm_recv(
                            mm=self.mm,
                            vm=server.hostname,
                            src=f"/iperf_server-log_client-{client.hostname}_server-{server.hostname}.log",
                            dst=os.path.join(self.base_dir, f"iperf_server-log_client-{client.hostname}_server-{server.hostname}.log"),
                        )

            # verify error field isn't set in iperf results
            for file in Path(self.base_dir).glob("*.json"):
                try:
                    data = utils.read_json(file)
                except Exception as ex:
                    self.eprint(f"failed to read iperf data from '{file}': {ex}")
                    sys.exit(1)

                if data.get("error"):
                    self.eprint(f"error field set for iperf data from '{file}': {data['error']}")
                    sys.exit(1)

            # Generate RTT histograms
            # TODO: generate histograms using matplotlib
            if self.metadata.get("create_histogram", True):
                self.print("generating RTT histograms (create_histogram=true)")
                for server in mapping.values():
                    for client in server.clients.values():
                        self.print(f"generating RTT histogram for client '{client.hostname}' and server '{server.hostname}'")
                        c_path = Path(self.base_dir, os.path.basename(client["client_log_path"]))
                        results = utils.read_json(c_path)  # type: dict

                        # get number of intervals using jq:
                        # cat iperf_client-data_client-br14_server-control-scada.json | jq '.intervals | length'
                        rtt_times = []
                        for interval in results["intervals"]:
                            rtt_times.append(utils.usec_to_sec(interval["streams"][0]["rtt"]))

                        # RTT text file contents, one value per line
                        # Limit the float precision to 6
                        hist_str = "\n".join(f"{t:.06f}" for t in rtt_times) + "\n"  # add final newline

                        # "iperf_server-data_client-load5_server-load8.json" => "load5_load8"
                        pair_name = c_path.name.replace(".json", "").split("-data_")[-1].replace("client-", "").replace("server-", "").replace("_", "-")

                        rtt_hist_file = Path(self.base_dir, f"rtt_histogram_{pair_name}.txt")
                        self.print(f"Writing RTT histogram to {rtt_hist_file} (client={client.hostname}, server={server.hostname})")
                        rtt_hist_file.write_text(hist_str, encoding="utf-8")
        else:
            self.print("using rperf, skipping data collection and processing")

        logger.log('INFO', f'Stopped user component: {self.name}')

    def cleanup(self):
        logger.log('INFO', f'Cleaning up user component: {self.name}')
        node_info = self._get_node_info()

        self.mm.clear_cc_prefix()

        if not self.metadata.get("use_rperf"):
            self._delete_all_iperf(node_info)

        for vm in node_info["vms"]:
            self.mm.clear_vm_tag(vm, "iperf")

        logger.log('INFO', f'Cleaned up user component: {self.name}')


def main():
    Iperf()


if __name__ == '__main__':
    main()
