import copy, json, os, sys

from box import Box


class AppBase(object):
    valid_stages = ["configure", "pre-start", "post-start", "cleanup"]

    @classmethod
    def check_stdin(klass):
        """
        Ensures that only one argument is passed in via the command line
        This takes in the stage as the first argument ?
        Need to make sure that if anything errors it takes it errors with a status code that is non-zero
        """

        if len(sys.argv) != 2:
            msg = f"must pass exactly one argument to phenix app: was passed {len(sys.argv) - 1}"

            klass.eprint(msg)
            klass.eprint("app expects <executable> <app_stage> << <json_input>")

            sys.exit(1)

        if sys.argv[1] not in klass.valid_stages:
            klass.eprint(f'{sys.argv[1]} is not a valid stage')
            klass.eprint(f'Valid stages are: {klass.valid_stages}')

            sys.exit(1)

    @staticmethod
    def eprint(*args):
        """
        Prints errors to STDERR
        """

        print(*args, file=sys.stderr)

    def __init__(self, name):
        self.name = name

        self.check_stdin()
        self.stage = sys.argv[1]

        # Keep this around just in case apps want direct access to it.
        self.raw_input = sys.stdin.read()

        # TODO: catch exceptions parsing JSON
        self.experiment = Box.from_json(self.raw_input)
        self.exp_name   = self.extract_experiment_name()
        self.exp_dir    = self.extract_experiment_dir()
        self.asset_dir  = self.extract_asset_dir()
        self.metadata   = self.extract_metadata()
        self.topo       = self.get_annotation('topology')
        os.makedirs(self.exp_dir, exist_ok=True)

    def execute_stage(self):
        """
        Executes the stage passed in from the json blob
        """

        stages_dict = {
            'configure'  : self.configure,
            'pre-start'  : self.pre_start,
            'post-start' : self.post_start,
            'cleanup'    : self.cleanup
        }

        stages_dict[self.stage]()

        # TODO: should we go ahead and print self.experiment to STDOUT here? If
        # we do, app developers won't be able to do any additional manipulation
        # to the experiment after the appropriate stage function has completed.

    def get_annotation(self, key):
        if 'annotations' in self.experiment.metadata:
            return self.experiment.metadata.annotations[key]

        return None

    def extract_app(self):
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == self.name:
                return app

    def extract_node(self, hostname):
        nodes = self.experiment.spec.topology.nodes

        for node in nodes:
            if node.general.hostname == hostname:
                return node

    def extract_nodes_topology_type(self, types):
        hosts = []

        if isinstance(types, str):
            types = [types]

        for host in self.experiment.spec.topology.nodes:
            node_type = host.type

            if node_type in types:
                hosts.append(host)

        return hosts

    def extract_all_nodes(self):
        app   = self.extract_app()
        hosts = []

        for host in app.hosts:
            hosts.append(copy.deepcopy(host))

        for host in hosts:
            node = self.extract_node(host.hostname)
            host.update({'topology': node})

        return hosts

    def extract_nodes_type(self, types):
        app   = self.extract_app()
        hosts = []

        if isinstance(types, str):
            types = [types]

        for host in app.hosts:
            node_type = host.metadata.get("type", None)

            if node_type in types:
                hosts.append(copy.deepcopy(host))

        for host in hosts:
            node = self.extract_node(host.hostname)
            host.update({'topology': node})

        return hosts

    def extract_nodes_label(self, labels):
        app   = self.extract_app()
        hosts = []

        if isinstance(labels, str):
            labels = [labels]

        for host in app.hosts:
            node_labels = host.metadata.get("labels", [])

            if isinstance(node_labels, str):
                if node_labels in labels:
                    hosts.append(copy.deepcopy(host))
            elif isinstance(node_labels, list):
                if any(item in node_labels for item in labels):
                    hosts.append(copy.deepcopy(host))
            elif str(node_labels) in labels:
                hosts.append(copy.deepcopy(host))

        for host in hosts:
            node = self.extract_node(host.hostname)
            host.update({'topology': node})

        return hosts

    def extract_experiment_name(self):
        return self.experiment.spec.experimentName

    def extract_experiment_dir(self):
        return self.experiment.spec.baseDir

    def extract_asset_dir(self):
        app = self.extract_app()

        return app.get('assetDir', None)

    def extract_metadata(self):
        app = self.extract_app()

        return app.get('metadata', None)

    def add_node(self, node):
        self.experiment.spec.topology.nodes.append(node)

    def add_inject(self, hostname, inject):
        node = self.extract_node(hostname)

        if node.get('injections', None):
            # First check to see if this exact injection already exists. This
            # would occur, for example, if an experiment gets started multiple
            # times. We don't raise an exception here since ultimately it's OK
            # if the injection already exists.
            for i in node.injections:
                if i.src == inject['src'] and i.dst == inject['dst']:
                    return

            node.injections.append(inject)
        else:
            # There was no injection list, so we put the
            # injection dictionary in a list.
            node['injections'] = [inject]

    def is_fully_scheduled(self):
        schedules = self.experiment.spec.schedules

        for node in self.experiment.spec.topology.nodes:
            name = node.general.hostname

            if name not in schedules:
                return False

        return True

    def configure(self):
        pass

    def pre_start(self):
        pass

    def post_start(self):
        pass

    def cleanup(self):
        pass
