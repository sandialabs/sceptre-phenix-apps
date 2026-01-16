import argparse
import copy
import os
import re
import sys
from typing import Any, Optional

from box import Box

from phenix_apps.common import utils
from phenix_apps.common.logger import configure_logging, logger


class AppBase(object):
    valid_stages = ["configure", "pre-start", "post-start", "running", "cleanup"]

    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        self.name = name
        self.stage = stage
        self.dryrun = dryrun

        # Keep this around just in case apps want direct access to it.
        self.raw_input = sys.stdin.read()

        try:
            self.experiment = Box.from_json(self.raw_input)
        except Exception:
            try:
                self.experiment = Box.from_yaml(self.raw_input)
            except Exception as ex:
                logger.error(
                    f"Failed to parse experiment input (JSON or YAML) for app '{self.name}': {ex}",
                )
                sys.exit(1)

        self.app = self.extract_app()
        if not self.app:
            logger.error(f"Failed to find app '{self.name}' in scenario metadata!")
            sys.exit(1)

        self.exp_name = self.experiment.spec.experimentName
        self.exp_dir = self.experiment.spec.baseDir
        self.asset_dir = self.app.get("assetDir", None)
        self.metadata = self.app.get("metadata", {})
        self.topo = self.get_annotation("topology")

        # Create the experiment directory if it doesn't exist
        os.makedirs(self.exp_dir, exist_ok=True)

        # Mako templates directory inside the app's code folder
        py_path = sys.modules[self.__class__.__module__].__file__
        self.templates_dir = utils.abs_path(py_path, "templates")

    @classmethod
    def main(cls, name: str):
        parser = argparse.ArgumentParser(description=f"phenix user app: {name}")
        parser.add_argument(
            "stage", choices=cls.valid_stages, help="Lifecycle stage to execute"
        )
        parser.add_argument("--dry-run", action="store_true", help="Perform a dry run")

        args = parser.parse_args()

        dryrun = args.dry_run or os.getenv("PHENIX_DRYRUN", "false") == "true"

        # Configure logger. In dry-run mode, force console output.
        configure_logging(force_console=dryrun)

        app = cls(name, args.stage, dryrun)
        app.execute_stage()
        app.finalize()

        # Output the experiment JSON (standard Phenix app behavior)
        if app.dryrun:
            print(app.experiment.to_json(indent=2))
        else:
            print(app.experiment.to_json())

        return app

    def execute_stage(self) -> None:
        """
        Executes the stage passed in from the json blob
        """

        stages_dict = {
            "configure": self.configure,
            "pre-start": self.pre_start,
            "post-start": self.post_start,
            "running": self.running,
            "cleanup": self.cleanup,
        }

        stages_dict[self.stage]()

    def finalize(self) -> None:
        pass

    def get_annotation(self, key: str) -> str | None:
        metadata = self.experiment.get("metadata")
        if metadata and "annotations" in metadata:
            return metadata.annotations.get(key)

        return None

    def extract_app(self, name: Optional[str] = None) -> Box | None:
        """
        Return the app definition from the Scenario matching "name",
        otherwise this app's definition if "name" is None.
        """

        name = self.name if not name else name
        apps = self.experiment.spec.scenario.apps

        for app in apps:
            if app.name == name:
                return app

    def extract_node(
        self, hostname: str, wildcard: bool = False
    ) -> Box | list[Box] | None:
        regex = re.compile(hostname)
        extracted = []

        for node in self.experiment.spec.topology.nodes:
            if wildcard:
                if regex.match(node.general.hostname):
                    extracted.append(node)
            else:
                if node.general.hostname == hostname:
                    return node

        if wildcard:
            return extracted
        else:
            return None

    def extract_topology_nodes_by_attribute(
        self, attribute: str, vals: str | list[str]
    ) -> list[Box]:
        hosts = []

        if isinstance(vals, str):
            vals = [vals]

        for node in self.experiment.spec.topology.nodes:
            node_attribute = node.get(attribute, {})

            # Could be a null entry in the JSON schema.
            if not node_attribute:
                continue

            for val in node_attribute.keys():
                if val in vals:
                    hosts.append(node)
                    break

        return hosts

    def extract_annotated_topology_nodes(
        self, annotations: str | list[str]
    ) -> list[Box]:
        """
        Return list of Topology nodes with any annotation attributes with keys
        that match "annotations" or are in the list "annotations".
        """

        return self.extract_topology_nodes_by_attribute("annotations", annotations)

    def extract_labelled_topology_nodes(self, labels: str | list[str]) -> list[Box]:
        """
        Return list of Topology nodes with any label attributes with keys
        that match "labels" or are in the list "labels".
        """

        return self.extract_topology_nodes_by_attribute("labels", labels)

    def extract_app_node(
        self, hostname: str, include_missing: bool = True
    ) -> Box | None:
        for host in self.app.get("hosts", []):
            if host.hostname == hostname:
                topo_node = self.extract_node(hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({"topology": topo_node})

                return node

        return None

    def extract_all_nodes(self, include_missing: bool = True) -> list[Box]:
        """
        Extract Topology nodes with hostnames that match the hostname
        defined in the "hosts" attribute in the Scenario metadata
        for this app.
        """

        hosts = []

        for host in self.app.get("hosts", []):
            topo_node = self.extract_node(host.hostname)

            if not topo_node and not include_missing:
                continue

            node = copy.deepcopy(host)
            node.update({"topology": topo_node})

            hosts.append(node)

        return hosts

    def extract_nodes_type(
        self, types: str | list[str], include_missing: bool = True
    ) -> list[Box]:
        """
        Extract Topology nodes with hostnames that match the hostname
        defined in the "hosts" attribute in the Scenario metadata
        for this app and have the type/types matching the "type"
        field in the Scenario metadata.
        """

        hosts = []

        if isinstance(types, str):
            types = [types]

        for host in self.app.get("hosts", []):
            node_type = host.metadata.get("type", None)

            if node_type in types:
                topo_node = self.extract_node(host.hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({"topology": topo_node})

                hosts.append(node)

        return hosts

    def extract_nodes_label(
        self, labels: str | list[str], include_missing: bool = True
    ) -> list[Box]:
        """
        Extract Topology nodes that match values in the "labels" attribute for each
        host in an app's "host" field in Scenario metadata.

        Note that this is *different* from "labels" in the Topology metadata,
        use "extract_labelled_topology_nodes" for those.
        """

        hosts = []

        if isinstance(labels, str):
            labels = [labels]

        for host in self.app.get("hosts", []):
            node_labels = host.metadata.get("labels", [])

            if isinstance(node_labels, str):
                if node_labels in labels:
                    topo_node = self.extract_node(host.hostname)

                    if not topo_node and not include_missing:
                        continue

                    node = copy.deepcopy(host)
                    node.update({"topology": topo_node})

                    hosts.append(node)
            elif isinstance(node_labels, list):
                if any(item in node_labels for item in labels):
                    topo_node = self.extract_node(host.hostname)

                    if not topo_node and not include_missing:
                        continue

                    node = copy.deepcopy(host)
                    node.update({"topology": topo_node})

                    hosts.append(node)
            elif str(node_labels) in labels:
                topo_node = self.extract_node(host.hostname)

                if not topo_node and not include_missing:
                    continue

                node = copy.deepcopy(host)
                node.update({"topology": topo_node})

                hosts.append(node)

        return hosts

    def extract_node_interface_ip(
        self, hostname: str, iface: str, include_mask: bool = False
    ) -> str | tuple[str, int] | None:
        """
        Returns str with IP address of the interface name for the matching host.
        If include_mask is True, then a tuple is returned with the IP and
        subnet mask integer.
        """

        node = self.extract_node(hostname)

        if iface:
            for i in node.network.interfaces:
                if i["name"] == iface and "address" in i:
                    if include_mask:
                        return i["address"], i["mask"]
                    else:
                        return i["address"]
        elif len(node.network.interfaces) > 0:
            i = node.network.interfaces[0]

            if "address" in i:
                if include_mask:
                    return i["address"], i["mask"]
                else:
                    return i["address"]

        return None

    def extract_node_hostname_for_ip(self, address: str) -> str | None:
        if ":" in address:
            address, _ = address.split(":", 1)

        nodes = self.experiment.spec.topology.nodes

        for node in nodes:
            for i in node.network.interfaces:
                if "address" in i and i["address"] == address:
                    return node.general.hostname

        return None

    def add_node(self, new_node: Box | dict, overwrite: bool = False) -> None:
        found = None

        for idx, node in enumerate(self.experiment.spec.topology.nodes):
            if node.general.hostname == new_node["general"]["hostname"]:
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

    def add_annotation(self, hostname: str, key: str, value: Any) -> None:
        node = self.extract_node(hostname)

        annotations = node.get("annotations", {})

        # Could be a null entry in the JSON schema.
        if not annotations:
            annotations = {}

        # This will override an existing annotation with the same key.
        annotations[key] = value
        node["annotations"] = annotations

    def add_label(self, hostname: str, key: str, value: str) -> None:
        node = self.extract_node(hostname)

        labels = node.get("labels", {})

        # Could be a null entry in the JSON schema.
        if not labels:
            labels = {}

        # This will override an existing label with the same key.
        labels[key] = value
        node["labels"] = labels

    def add_inject(self, hostname: str, inject: Box | dict) -> None:
        node = self.extract_node(hostname)

        if node.get("injections", None):
            # First check to see if this exact injection already exists. This
            # would occur, for example, if an experiment gets started multiple
            # times. We don't raise an exception here since ultimately it's OK
            # if the injection already exists.
            for i in node.injections:
                if i.src == inject["src"] and i.dst == inject["dst"]:
                    return

            node.injections.append(inject)
        else:
            # There was no injection list, so we put the
            # injection dictionary in a list.
            node["injections"] = [inject]

    def is_booting(self, hostname: str) -> bool:
        node = self.extract_node(hostname)
        dnb = node.general.get("do_not_boot", False)

        return not dnb

    def is_fully_scheduled(self) -> bool:
        schedules = self.experiment.spec.schedules

        for node in self.experiment.spec.topology.nodes:
            name = node.general.hostname

            if name not in schedules:
                return False

        return True

    def render(self, template_name: str, file_path: str, **kwargs) -> str:
        """
        Render a Mako template from the app's "templates" directory
        and write it to the specified file path.
        The target file path should be absolute.
        The template_name must be the full name of the mako template,
        including the ".mako" extension

        Returns the file path written to.
        """

        with open(file_path, "w") as fp:
            utils.mako_serve_template(
                template_name=template_name,
                templates_dir=self.templates_dir,
                filename=fp,
                **kwargs,
            )

        return file_path

    def configure(self) -> None:
        pass

    def pre_start(self) -> None:
        pass

    def post_start(self) -> None:
        pass

    def running(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
