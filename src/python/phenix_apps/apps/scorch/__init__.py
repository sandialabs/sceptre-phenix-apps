import json, os, signal, sys, time

from phenix_apps.common.settings import PHENIX_DIR

from box import Box

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
    def eprint(msg, ui=True):
        """
        Prints errors to STDERR, and optionally flushed to STDOUT so it also
        gets streamed to the phenix UI.
        """

        print(msg, file=sys.stderr)

        if ui:
            tstamp = time.strftime('%H:%M:%S')
            print(f'[{tstamp}] ERROR : {msg}', flush=True)

    @staticmethod
    def print(msg, ts=True):
        """
        Prints msg to STDOUT, flushing it immediately so it gets streamed to the
        phenix UI in a timely manner.
        """

        if ts:
            tstamp = time.strftime('%H:%M:%S')
            print(f'[{tstamp}] {msg}', flush=True)
        else:
            print(msg, flush=True)

    def __init__(self, typ):
        self.type = typ

        self.dryrun = os.getenv('PHENIX_DRYRUN', 'false') == 'true'

        self.check_stdin()

        self.stage = sys.argv[1]
        self.name  = sys.argv[2]
        self.run   = int(sys.argv[3])
        self.loop  = int(sys.argv[4])
        self.count = int(sys.argv[5])

        # Keep this around just in case components want direct access to it.
        self.raw_input = sys.stdin.read()

        # TODO: catch exceptions parsing JSON
        self.experiment = Box.from_json(self.raw_input)
        self.exp_name   = self.experiment.spec.experimentName
        self.exp_dir    = self.experiment.spec.baseDir
        self.metadata   = self.extract_metadata()

        self.files_dir = os.getenv('PHENIX_FILES_DIR', f'{PHENIX_DIR}/images/{self.exp_name}/files')
        self.base_dir  = f'{self.files_dir}/scorch/run-{self.run}/{self.name}/loop-{self.loop}-count-{self.count}'
        os.makedirs(self.base_dir, exist_ok=True)

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

    def mm_init(self, namespaced=True):
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

    def extract_metadata(self):
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == 'scorch':
                md = app.get('metadata', None)

                if not md: return

                for cmp in md.components:
                    if cmp.name == self.name and cmp.type == self.type:
                        return cmp.get('metadata', None)

    def extract_node_names(self):
        nodes = []

        for node in self.experiment.spec.topology.nodes:
            nodes.append(node.general.hostname)

        return nodes

    def extract_node_interface_index(self, name, iface):
        for node in self.experiment.spec.topology.nodes:
            if node.general.hostname == name:
                for idx, i in enumerate(node.network.interfaces):
                    if i.name == iface:
                        return idx

                raise ValueError(f'interface {iface} does not exist on node {name}')

        raise ValueError(f'node {name} does not exist')

    def extract_node_ip(self, name, iface):
        # TODO: consider using minimega client to get IP address so things "just
        # work" even if DHCP is being used for the interface.

        for node in self.experiment.spec.topology.nodes:
            if node.general.hostname == name:
                for i in node.network.interfaces:
                    if i.name == iface:
                        return i.address

                raise ValueError(f'interface {iface} does not exist on node {name}')

        raise ValueError(f'node {name} does not exist')

    def configure(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def cleanup(self):
        pass
