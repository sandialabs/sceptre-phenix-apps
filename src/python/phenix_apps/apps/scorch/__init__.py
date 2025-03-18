import os
import re
import signal
import sys
import time
from typing import List, Optional, Tuple, Union
from pathlib import Path

from phenix_apps.common.settings import PHENIX_DIR
from phenix_apps.common import logger, utils

from box import Box
from elasticsearch import Elasticsearch
import minimega


class ComponentBase(object):
    valid_stages = ["configure", "start", "stop", "cleanup"]

    @classmethod
    def check_stdin(klass):
        """
        Ensures that only one argument is passed in via the command line
        This takes in the stage as the first argument ?
        Need to make sure that if anything errors it takes it errors with a status code that is non-zero
        """

        if len(sys.argv) != 6:
            klass.eprint(f'must pass exactly five arguments to scorch component: was passed {len(sys.argv) - 1}')
            klass.eprint("scorch component expects <run_stage> <component_name> <run_id> <current_loop> <current_loop_count> << <json_input>")

            sys.exit(1)

        if sys.argv[1] not in klass.valid_stages:
            klass.eprint(f'{sys.argv[1]} is not a valid stage')
            klass.eprint(f'Valid stages are: {klass.valid_stages}')

            sys.exit(1)

    @staticmethod
    def eprint(msg: str, ui: bool = True):
        """
        Prints errors to STDERR, and optionally flushed to STDOUT so it also
        gets streamed to the phenix UI.
        """

        print(msg, file=sys.stderr)

        if ui:
            tstamp = time.strftime('%H:%M:%S')
            print(f'[{tstamp}] ERROR : {msg}', flush=True)

        logger.log("ERROR", msg)  # write error to phenix log file

    @staticmethod
    def print(msg: str, ts: bool = True):
        """
        Prints msg to STDOUT, flushing it immediately so it gets streamed to the
        phenix UI in a timely manner.
        """

        if ts:
            tstamp = time.strftime('%H:%M:%S')
            print(f'[{tstamp}] {msg}', flush=True)
        else:
            print(msg, flush=True)

    def __init__(self, typ: str):
        self.type = typ

        self.dryrun = os.getenv('PHENIX_DRYRUN', 'false') == 'true'

        self.check_stdin()

        self.stage = sys.argv[1]  # stage name, one of: configure, start, stop, cleanup
        self.name  = sys.argv[2]  # component name (name given to component by the user in the Scorch app configuration)
        self.run   = int(sys.argv[3])  # Run number, usually 0 unless multiple runs are defined in scenario
        self.loop  = int(sys.argv[4])  # Loop number, usually 0 unless loops are defined, then it's...always 1?
        self.count = int(sys.argv[5])  # Run iteration, usually 0 unless "count: <num>" is specified (multiple iterations of same run or loop)

        # Keep this around just in case components want direct access to it.
        self.raw_input = sys.stdin.read()

        try:
            self.experiment = Box.from_json(self.raw_input)
        except Exception as ex:
            self.eprint(f"Failed to parse experiment JSON: {ex}")
            sys.exit(1)

        self.exp_name   = self.experiment.spec.experimentName
        self.exp_dir    = self.experiment.spec.baseDir
        self.metadata   = self.extract_metadata()

        self.root_dir  = os.path.join(PHENIX_DIR, 'images')
        self.files_dir = os.getenv('PHENIX_FILES_DIR', os.path.join(self.root_dir, self.exp_name, 'files'))
        self.base_dir  = os.path.join(self.files_dir, f'scorch/run-{self.run}/{self.name}/loop-{self.loop}-count-{self.count}')

        os.makedirs(self.base_dir, exist_ok=True)

        self._mm = None  # minimega instance
        self._es = None  # Elasticsearch instance

        def signal_handler(signum, stack):
            pass

        # handle signals for backgrounded components
        signal.signal(signal.SIGTERM, signal_handler)

    def execute_stage(self):
        """
        Executes the stage passed in from the json blob
        """

        stages_dict = {
            'configure' : self.configure,
            'start'     : self.start,
            'stop'      : self.stop,
            'cleanup'   : self.cleanup
        }

        stages_dict[self.stage]()

    @property
    def mm(self) -> minimega.minimega:
        """
        minimega instance that's initialized the first time it's referenced.
        """
        if not self._mm:
            self._mm = self.mm_init()
        return self._mm

    @mm.setter
    def mm(self, mm_obj: minimega.minimega):
        self._mm = mm_obj

    def mm_init(self, namespaced: bool = True) -> minimega.minimega:
        """
        The minimega.connect function will print a message to STDOUT if there is
        a version mismatch. This utility function prevents that from happening.
        """

        sys.stdout = open('/dev/null', 'w')

        mm = None

        if namespaced:
            mm = minimega.connect(namespace=self.exp_name)
        else:
            mm = minimega.connect()

        sys.stdout.close()
        sys.stdout = sys.__stdout__

        return mm

    @property
    def es(self) -> Elasticsearch:
        """Connect to Elasticsearch and return the initialized object."""
        if not self._es:
            self.print(f"Connecting to Elasticsearch: {self.metadata.elasticsearch.server}")
            self._es = utils.connect_elastic(self.metadata.elasticsearch.server)
        return self._es

    @es.setter
    def es(self, es: Elasticsearch) -> None:
        self._es = es

    def extract_metadata(self) -> Optional[Box]:
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == 'scorch':
                md = app.get('metadata', None)

                if not md:
                    return None

                for cmp in md.components:
                    if cmp.name == self.name and cmp.type == self.type:
                        return cmp.get('metadata', None)

    def extract_run_name(self) -> Optional[str]:
        app = self.extract_app("scorch")
        if not app:
            return None

        md = app.get('metadata', {})
        runs = md.get('runs', [])

        if len(runs) <= self.run:
            return str(self.run)

        name = runs[self.run].get('name', str(self.run))

        # name might be an empty string...
        return name if name else str(self.run)

    def extract_app(self, name: str) -> Optional[Box]:
        for app in self.experiment.spec.scenario.apps:
            if app.name == name:
                return app
        self.eprint(f"failed to find app '{name}'")

    def extract_node(self, hostname: str, wildcard: bool = False) -> Optional[Box]:
        if wildcard:
            extracted = []
            regex = re.compile(hostname)

            for node in self.experiment.spec.topology.nodes:
                if regex.match(node.general.hostname):
                    extracted.append(node)

            return extracted
        else:
            for node in self.experiment.spec.topology.nodes:
                if node.general.hostname == hostname:
                    return node

            return None

    def extract_node_names(self) -> list:
        nodes = []

        for node in self.experiment.spec.topology.nodes:
            nodes.append(node.general.hostname)

        return nodes

    def extract_node_ip(self, name: str, iface: str) -> str:
        # TODO: consider using minimega client to get IP address so things "just
        # work" even if DHCP is being used for the interface.

        for node in self.experiment.spec.topology.nodes:
            if node.general.hostname == name:
                for i in node.network.interfaces:
                    if i.name == iface:
                        return i.address

                raise ValueError(f'interface {iface} does not exist on node {name}')

        raise ValueError(f'node {name} does not exist')

    def get_host_and_iface(self, config: Box) -> Tuple[str, int]:
        """
        Extract the hostname and interface fields from metadata, and resolve them on the node.
        The 'interface' field in the config can either be a index (0) or a name (eth0).
        The name must match the name of an interface on the nodes in the topology.

        Returns:
            tuple with the hostname and the interface index
        """
        hostname = config.get('hostname')
        if not hostname:
            self.eprint(f'no hostname provided for VM config {config}')
            sys.exit(1)

        node = self.extract_node(hostname)
        if not node:
            self.eprint(f'failed to find node "{hostname}" (config={config})')
            sys.exit(1)

        if not node.network.interfaces:
            self.eprint(f'no interfaces defined for node {hostname}! (node={node}, config={config})')
            sys.exit(1)

        # Default to interface 0
        interface = config.get('interface', 0)

        # If it's an integer, use as-is
        # If not, attempt to resolve the name to a index
        try:
            interface = int(interface)
        except ValueError:
            for idx, if_val in enumerate(node.network.interfaces):
                if if_val.name == interface:
                    interface = idx
                    break
            else:
                raise ValueError(f'interface {interface} does not exist on node {hostname}')

        return hostname, interface

    def recv_file(self, vm: str, src: Union[List[str], str], dst: str = "") -> None:
        if not dst and isinstance(src, str):
            dst = os.path.join(self.base_dir, Path(src).name)
        elif not dst and isinstance(src, list):
            dst = self.base_dir

        self.print(f"copying file from {vm} (src={src}, dst={dst})")

        try:
            utils.mm_recv(self.mm, vm, src, dst)
            self.print(f"file '{src}' received from VM {vm} to {dst}")
        except Exception as ex:
            self.eprint(f"error receiving file '{src}' from VM {vm}: {ex}")
            sys.exit(1)

    def ensure_vm_running(self, vm: str):
        self.print(f"Checking if VM is running (VM hostname: {vm})")
        vm_info = utils.mm_info_for_vm(self.mm, vm)
        if not vm_info or vm_info["state"].lower() != "running":
            self.eprint(f"VM isn't running (vm name: {vm})")
            sys.exit(1)

    def run_and_check_command(
        self,
        vm: str,
        cmd: str,
        timeout: float = 5.0,
        poll_rate: float = 0.5,
        debug: bool = False,
    ) -> dict:
        """
        Run and wait for command, and if exit code is non-zero, print error and exit.
        """
        resp = utils.mm_exec_wait(
            mm=self.mm,
            vm=vm,
            cmd=cmd,
            timeout=timeout,
            poll_rate=poll_rate,
            debug=debug,
        )

        if resp["exitcode"] != 0:
            self.eprint(f"failed to run '{cmd}'\nexitcode: {resp['exitcode']}\nstdout: {resp['stdout']}\nstderr: {resp['stderr']}")
            sys.exit(1)

        return resp

    def check_process_running(
        self, vm: str, process: str, os_type: str = "linux"
    ) -> bool:
        if os_type == "linux":
            # "ps -e" cuts off full command name, need "f" to get full command
            ps_list = self.run_and_check_command(vm, "ps -ef", timeout=15.0, poll_rate=0.5)["stdout"]
        elif os_type == "windows":
            ps_list = self.run_and_check_command(vm, "tasklist", timeout=15.0, poll_rate=0.5)["stdout"]
        else:
            raise ValueError(f"unknown os_type '{os_type}' for VM {vm}")

        if process.lower() in ps_list.lower():
            return True
        else:
            self.eprint(f"process '{process}' is not running on '{vm}'")
            return False

    def configure(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def cleanup(self):
        pass
