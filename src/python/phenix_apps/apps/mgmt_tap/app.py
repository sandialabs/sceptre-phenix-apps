import ipaddress
import socket

import minimega

from phenix_apps.apps import AppBase
from phenix_apps.common.logger import logger
from phenix_apps.common.utils import _mm_init, mm_compute_cmd, mm_host_info


class MgmtTap(AppBase):
    """Management tap user application

    This user application will create a tap on the management network of the
    experiment it is assigned to, allowing a user to copy files to and from
    machines in the network as long as the vm has a connection to the
    management network.

    E.g.
        - name: mgmt_tap
          metadata:
            subnet: 172.16.0.0/16
            vlan: MGMT_1
    """

    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)
        # Check if subnet and namespace is specified in app metadata
        self.subnet = self.metadata.get("subnet", None) if self.metadata else None
        self.vlan = self.metadata.get("vlan", "MGMT") if self.metadata else "MGMT"
        # Must limit the tap_name to 14 characters. minimega won't create the host taps otherwise
        self.exp_name = self.exp_name[:9]
        self.vlan_name = self.exp_name[:4]
        self.tap = f"{self.exp_name}_{self.vlan_name.lower()}"
        self.ns = f"{self.exp_name}_net"
        self._mm = None  # minimega connection
        # Get list of mesh hosts
        self.hosts = self._get_hosts()
        if not self.hosts:
            logger.error("No hosts found in 'mgmt_tap' application!")
            raise RuntimeError("No hosts found in mgmt_tap application")
        self.hostname = socket.gethostname().split("-")[0]

    def _get_mm_connection(self) -> minimega.minimega:
        """Get or create minimega connection."""
        if self._mm is None:
            try:
                self._mm = _mm_init()
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
        # Create tap
        vlan = self.experiment.status.vlans.get(self.vlan, None)
        if vlan is None:
            logger.error(f"Cannot find VLAN ID for alias {self.vlan}")
            raise RuntimeError("Cannot find VLAN ID for alias {self.vlan}")
        if self.subnet:
            network = ipaddress.ip_network(self.subnet, strict=False)
        else:
            network = ipaddress.ip_network("172.16.0.0/16", strict=False)
        hosts = network.hosts()

        for _idx, host in enumerate(self.hosts, start=1):
            try:
                ip_addr = next(hosts)
            except StopIteration as err:
                logger.error("Ran out of IP addresses on host")
                raise RuntimeError("Ran out of IP addresses on host") from err

            ip_ = f"{ip_addr}/{network.prefixlen}"
            logger.debug(f"Creating host tap {ip_} on {host}")
            kwargs = {
                "experiment": self.exp_name,
                "computes": host,
                "command_type": "tap",
                "command": f"create {vlan} bridge phenix ip {ip_} {self.tap}",
                "ignore_error": True,
            }
            mm_obj = self._get_mm_connection()
            mm_compute_cmd(mm_obj, **kwargs)
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
        logger.info(f"Completed cleanup for user application: {self.name}")
