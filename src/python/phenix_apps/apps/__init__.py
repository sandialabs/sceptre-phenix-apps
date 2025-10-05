import copy, os, ipaddress, re, sys

from box import Box


class AppBase(object):
    valid_stages = ["configure", "pre-start", "post-start", "running", "cleanup"]

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

        self.dryrun = os.getenv('PHENIX_DRYRUN', 'false') == 'true'

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
            'running'    : self.running,
            'cleanup'    : self.cleanup
        }

        sys.stdout = open('/dev/null', 'w')

        stages_dict[self.stage]()

        sys.stdout.close()
        sys.stdout = sys.__stdout__

    def get_annotation(self, key):
        if 'annotations' in self.experiment.metadata:
            return self.experiment.metadata.annotations[key]

        return None

    def extract_app(self, name = None):
        name = self.name if not name else name
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == name:
                return app

    def extract_node(self, hostname, wildcard = False):
        nodes = self.experiment.spec.topology.nodes
        regex = re.compile(hostname)
        extracted = []

        for node in nodes:
            if wildcard:
                if regex.match(node.general.hostname):
                    extracted.append(node)
            else:
                if node.general.hostname == hostname:
                    return node

        if wildcard:
            return extracted
        return None

    def extract_annotated_topology_nodes(self, annotations):
        nodes = self.experiment.spec.topology.nodes
        hosts = []

        if isinstance(annotations, str):
            annotations = [annotations]

        for node in nodes:
            node_annotations = node.get('annotations', {})

            # Could be a null entry in the JSON schema.
            if not node_annotations:
                continue

            for annotation in node_annotations.keys():
                if annotation in annotations:
                    hosts.append(node)
                    break

        return hosts

    def extract_app_node(self, hostname, include_missing = True):
        app = self.extract_app()

        for host in app.get("hosts", []):
            if host.hostname == hostname:
                topo_node = self.extract_node(hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({'topology': topo_node})

                return node

        return None

    def extract_nodes_topology_type(self, types):
        hosts = []

        if isinstance(types, str):
            types = [types]

        for host in self.experiment.spec.topology.nodes:
            node_type = host.type

            if node_type in types:
                hosts.append(host)

        return hosts

    def extract_all_nodes(self, include_missing = True):
        app   = self.extract_app()
        hosts = []

        for host in app.get("hosts", []):
            topo_node = self.extract_node(host.hostname)

            if not topo_node and not include_missing:
                continue

            node = copy.deepcopy(host)
            node.update({'topology': topo_node})

            hosts.append(node)

        return hosts

    def extract_nodes_type(self, types, include_missing = True):
        app   = self.extract_app()
        hosts = []

        if isinstance(types, str):
            types = [types]

        for host in app.get("hosts", []):
            node_type = host.metadata.get("type", None)

            if node_type in types:
                topo_node = self.extract_node(host.hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({'topology': topo_node})

                hosts.append(node)

        return hosts

    def extract_nodes_label(self, labels, include_missing = True):
        app   = self.extract_app()
        hosts = []

        if isinstance(labels, str):
            labels = [labels]

        for host in app.get("hosts", []):
            node_labels = host.metadata.get("labels", [])

            if isinstance(node_labels, str):
                if node_labels in labels:
                    topo_node = self.extract_node(host.hostname)

                    if not topo_node and not include_missing:
                        continue

                    node = copy.deepcopy(host)
                    node.update({'topology': topo_node})

                    hosts.append(node)
            elif isinstance(node_labels, list):
                if any(item in node_labels for item in labels):
                    topo_node = self.extract_node(host.hostname)

                    if not topo_node and not include_missing:
                        continue

                    node = copy.deepcopy(host)
                    node.update({'topology': topo_node})

                    hosts.append(node)
            elif str(node_labels) in labels:
                topo_node = self.extract_node(host.hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({'topology': topo_node})

                hosts.append(node)

        return hosts

    def extract_labeled_nodes(self, labels):
        return self.extract_nodes_label(labels)

    def extract_experiment_name(self):
        return self.experiment.spec.experimentName

    def extract_experiment_dir(self):
        return self.experiment.spec.baseDir

    def extract_asset_dir(self):
        app = self.extract_app()

        return app.get('assetDir', None)

    def extract_metadata(self):
        app = self.extract_app()

        return app.get('metadata', {})

    def extract_node_metadata(self, hostname):
        app = self.extract_app()

        for host in app.get("hosts", []):
            if host.hostname == hostname:
                return host.metadata

        return {}

    def extract_node_interface_ip(self, hostname, iface, include_mask = False):
        node = self.extract_node(hostname)

        if iface:
            for i in node.network.interfaces:
                if i['name'] == iface and 'address' in i:
                    if include_mask:
                        return i['address'], i['mask']
                    else:
                        return i['address']
        elif len(node.network.interfaces) > 0:
            i = node.network.interfaces[0]

            if 'address' in i:
                if include_mask:
                    return i['address'], i['mask']
                else:
                    return i['address']

        return None

    def extract_node_hostname_for_ip(self, address):
        if ':' in address:
            address, _ = address.split(':', 1)

        nodes = self.experiment.spec.topology.nodes

        for node in nodes:
            for i in node.network.interfaces:
                if 'address' in i and i['address'] == address:
                    return node.general.hostname

        return None

    # create a node based on yaml and default values
    def create_node(self, md, hname, image = 'miniccc.qc2',
                    os_type = 'linux', vcpus = 2, memory = 4096):
        '''
        can take a minimal node definition in md, ex:
        - hostname: hosty
          os_type: linux
          vcpus: 4
          memory: 8192
          image: miniccc.qc2
          interfaces:
            - name: IF0
              address: 172.16.0.10/24
              gateway: 172.16.0.1
              vlan: MGMT
            - name: IF1
              address: 1.2.3.4/24
              gateway: 1.2.3.1
              vlan: INT

        md is not required, node can be constructed from named arguments
        '''

        hostname = md.get('hostname', hname)
        node = self.extract_node(hostname, wildcard=False)
        if not node:
            node = {
                'type': 'VirtualMachine',
                'general': {
                    'hostname' : hostname,
                    'vm_type'  : 'kvm'
                },
                'hardware': {
                    'os_type' : md.get('os_type', os),
                    'vcpus'   : md.get('vcpus', cpu),
                    'memory'  : md.get('memory', memory),
                    'drives'  : [
                        {'image': md.get('image', image)},
                    ]
                },
                'network': {
                    'interfaces':
                        self.create_interfaces(md.get('interfaces', []))
                }
            }
        return node

    def create_interfaces(self, ifaces):
        '''
        can take a minimal interface definitions in ifaces, ex:
        - name: IF0
          address: 172.16.0.10/24
          gateway: 172.16.0.1
          vlan: MGMT
        - name: IF1
          address: 1.2.3.4/24
          gateway: 1.2.3.1
          vlan: INT
        '''

        interfaces = []
        for idx, iface in enumerate(ifaces):
            ip = ipaddress.ip_interface(iface.get('address', '0.0.0.0/24'))
            name = iface.get('name', [])
            if not name:
                name = f'IF{idx}'
            interface = {
                'name'    : name,
                'type'    : 'ethernet',
                'proto'   : 'static',
                'address' : str(ip.ip),
                'mask'    : ip.network.prefixlen,
                'gateway' : iface.get('gateway', None),
                'vlan'    : iface.get('vlan', None)
            }
            interfaces.append(interface)
        return interfaces

    def add_node(self, new_node, overwrite = False):
        found = None

        for idx, node in enumerate(self.experiment.spec.topology.nodes):
            if node.general.hostname == new_node['general']['hostname']:
                found = idx
                break

        # If we didn't find an existing node, just append the new node.
        # If there is an existing node and the overwrite arg is set,
        # overwrite it with the new node, otherwise do nothing. Check
        # if found is None since found (idx) could be 0.
        if found is None:
            self.experiment.spec.topology.nodes.append(new_node)
        elif overwrite:
            self.experiment.spec.topology.nodes[found] = Box(new_node)

    def add_annotation(self, hostname, key, value):
        node = self.extract_node(hostname)

        annotations = node.get('annotations', {})

        # Could be a null entry in the JSON schema.
        if not annotations:
            annotations = {}

        # This will override an existing annotation with the same key.
        annotations[key] = value
        node['annotations'] = annotations

    def add_label(self, hostname, key, value):
        node = self.extract_node(hostname)

        labels = node.get('labels', {})

        # Could be a null entry in the JSON schema.
        if not labels:
            labels = {}

        # This will override an existing label with the same key.
        labels[key] = value
        node['labels'] = labels

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

    def add_interfaces(self, hostname, interfaces):
        node = self.extract_node(hostname)
        existing = [i['name'] for i in node['network']['interfaces']]

        new_ifaces = self.create_interfaces(interfaces)
        i = 0
        for ni in new_ifaces:
            if ni['name'] in existing:
                while f'IF{i}' in existing:
                    i += 1
                ni['name'] = f'IF{i}'
            existing.append(ni['name'])

        node['network']['interfaces'].append(new_ifaces)
        return node

    def is_booting(self, hostname):
        node = self.extract_node(hostname)
        dnb  = node.general.get('do_not_boot', False)

        return not dnb

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

    def running(self):
        pass

    def cleanup(self):
        pass
