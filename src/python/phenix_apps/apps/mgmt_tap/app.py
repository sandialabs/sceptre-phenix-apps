import socket
import sys

import minimega

from phenix_apps.apps import AppBase
from phenix_apps.common.logger import logger
from phenix_apps.common.utils import mm_compute_cmd, mm_host_info


class MgmtTap(AppBase):
    """Management tap user application

    This user application will create a tap on the management network of the
    experiment it is assigned to, allowing a user to copy files to and from
    machines in the network as long as the vm has a connection to the
    management network.

    If 'namespace' is set to 'True' in the app metadata, then this app creates
    the tap within an ip namespace. The namespace is named <experiment_name>_net.
    This way multiple experiments on the same compute node that use the same IP
    address space can be accessed individually.

    To access a VM on a specific experiment using namespaces, first the correct
    namespace must be used then a command should be provided. For example, if
    you wanted to copy a file to a VM in an experiment named 'foo', you would
    run a command similar to the below from the compute node:

        docker exec -it minimega ip netns exec foo_net \
            scp some_file.txt <VM User>@<IP of VM>:<destination>
        docker exec -it minimega ip netns exec foo_net \
            scp some_file.txt ubuntu@172.16.0.254:/home/ubuntu

    If you wanted to ssh to a VM:

        docker exec -it minimega ip netns exec foo_net \
            ssh root@172.16.31.101

    If you are not using docker, you would remove the docker portion of the
    command:

        ip netns exec foo_net scp some_file.txt <VM User>@<IP of VM>:<destination>
        ip netns exec foo_net scp some_file.txt ubuntu@172.16.0.254:/home/ubuntu
        ip netns exec foo_net ssh root@172.16.31.101

    E.g.
        - name: mgmt_tap
          metadata:
            subnet: 172.16.0.0/16
            namespace: True
    """

    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)
        # Check if subnet and namespace is specified in app metadata
        self.subnet = self.metadata.get("subnet", None) if self.metadata else None
        self.namespace = self.metadata.get("namespace", None) if self.metadata else None
        # Must limit the tap_name to 14 characters. minimega won't create the host taps otherwise
        self.exp_name = self.exp_name[:9]
        self.tap = f"{self.exp_name}_mgmt"
        self.ns = f"{self.exp_name}_net"
        self._mm = None  # minimega connection
        # Get list of mesh hosts
        self.hosts = self._get_hosts()
        if not self.hosts:
            logger.error("No hosts found in 'mgmt_tap' application!")
            raise RuntimeError("No hosts found in mgmt_tap application")
        self.hostname = socket.gethostname().split("-")[0]

    def _mm_init(self, namespaced: bool = True) -> minimega.minimega:
        """
        The minimega.connect function will print a message to STDOUT if there is
        a version mismatch. This utility function prevents that from happening.
        """

        saved_stdout = sys.stdout

        sys.stdout = open("/dev/null", "w")

        mm = None

        if namespaced:
            mm = minimega.connect(namespace=self.exp_name)
        else:
            mm = minimega.connect()

        sys.stdout.close()
        sys.stdout = saved_stdout

        return mm

    def _get_mm_connection(self) -> minimega.minimega:
        """Get or create minimega connection."""
        if self._mm is None:
            try:
                pass
                self._mm = self._mm_init()
            except Exception as e:
                logger.error(f"Failed to connect to minimega: {e}")
                raise RuntimeError(f"Failed to connect to minimega: {e}") from e
        return self._mm

    def _get_hosts(self) -> list[str]:
        """Get list of host names from minimega."""
        try:
            mm_obj = self._get_mm_connection()
            hosts = mm_host_info(mm_obj)
            return [x["name"] for x in hosts]
        except Exception as e:
            logger.error(f"Failed to get host information: {e}")
            raise RuntimeError(f"Failed to get host information: {e}") from e

    def post_start(self):
        logger.info(f"Running post_start for user application: {self.name}")
        # Create tap on management network
        mgmt_vlan = self.experiment.status.vlans.get("MGMT", None)
        if mgmt_vlan is None:
            logger.error("Cannot find VLAN ID for alias 'MGMT'")
            raise RuntimeError("Cannot find VLAN ID for alias 'MGMT'")
        for idx, host in enumerate(self.hosts, start=1):
            if self.subnet:
                [ip, subnet] = self.subnet.split("/")
                ip = ip.split(".")
                ip[3] = f"{idx}"
                ip_ = "/".join([".".join(ip), subnet])
            else:
                ip_ = f"172.16.111.{idx}/16"
            # add tap for this host
            logger.debug(f"Creating host tap on {host}")
            kwargs = {
                "experiment": self.exp_name,
                "computes": host,
                "command_type": "tap",
                "command": (f"create {mgmt_vlan} bridge phenix ip {ip_} {self.tap}"),
                "ignore_error": True,
            }
            mm_obj = self._get_mm_connection()
            mm_compute_cmd(mm_obj, **kwargs)
            if self.namespace:
                logger.debug(f"Creating netns {self.ns} on {host}")
                # create network namespace
                cmd = f"ip netns add {self.ns}"
                mm_obj = self._get_mm_connection()
                mm_compute_cmd(
                    mm_obj, experiment=self.exp_name, computes=host, command=cmd
                )
                # move tap to namespace (clears IP)
                cmd = f"ip link set dev {self.tap} netns {self.ns}"
                mm_obj = self._get_mm_connection()
                mm_compute_cmd(
                    mm_obj, experiment=self.exp_name, computes=host, command=cmd
                )
                # assign IP address to the tap
                cmd = f"ip netns exec {self.ns} ip addr add {ip_} dev {self.tap}"
                mm_obj = self._get_mm_connection()
                mm_compute_cmd(
                    mm_obj, experiment=self.exp_name, computes=host, command=cmd
                )
                # activate the network connection
                cmd = f"ip netns exec {self.ns} ip link set dev {self.tap} up"
                mm_obj = self._get_mm_connection()
                mm_compute_cmd(
                    mm_obj, experiment=self.exp_name, computes=host, command=cmd
                )
        logger.info(f"Completed post_start for user application: {self.name}")

    def cleanup(self):
        logger.info(f"Running cleanup for user application: {self.name}")
        # remove management network tap
        for _, host in enumerate(self.hosts, start=1):
            kwargs = {
                "experiment": self.exp_name,
                "computes": host,
                "command_type": "tap",
                "command": f"delete {self.tap}",
                "ignore_error": True,
            }
            mm_obj = self._get_mm_connection()
            mm_compute_cmd(mm_obj, **kwargs)
            if self.namespace:
                # remove the network namespace
                cmd = f"ip netns delete {self.ns}"
                mm_obj = self._get_mm_connection()
                mm_compute_cmd(
                    mm_obj, experiment=self.exp_name, computes=host, command=cmd
                )
        logger.info(f"Completed cleanup for user application: {self.name}")
