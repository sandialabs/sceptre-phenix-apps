import socket, sys

from phenix_apps.apps import AppBase
from phenix_apps.common import logger, utils

import phenix.services.minimega as mm


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
    def __init__(self):
        AppBase.__init__(self, 'mgmt_tap')
        # Check if subnet and namespace is specified in app metadata
        self.subnet = self.metadata.get('subnet', None) if self.metadata else None
        self.namespace = self.metadata.get('namespace', None) if self.metadata else None
        # Must limit the tap_name to 14 characters. minimega won't create the host taps otherwise
        self.exp_name = self.exp_name[:9]
        self.tap = f"{self.exp_name}_mgmt"
        self.ns = f"{self.exp_name}_net"
        # Get list of mesh hosts
        self.hosts = [x['name'] for x in mm.host_info()]
        if not self.hosts:
            logger.log('ERROR', "No hosts found in 'mgmt_tap' application!")
            sys.exit(1)
        self.hostname = socket.gethostname().split('-')[0]
        self.execute_stage()
        # We don't (currently) let the parent AppBase class handle this step
        # just in case app developers want to do any additional manipulation
        # after the appropriate stage function has completed.
        print(self.experiment.to_json())

    def post_start(self):
        logger.log('INFO', f"Running post_start for user application: {self.name}")
        # Create tap on management network
        mgmt_vlan = self.experiment.status.vlans.get('MGMT', None)
        if mgmt_vlan == None:
            logger.log('ERROR', "Cannot find VLAN ID for alias 'MGMT'")
            sys.exit(1)
        for idx, host in enumerate(self.hosts, start=1):
            if self.subnet:
                [ip, subnet] = self.subnet.split('/')
                ip = ip.split('.')
                ip[3] = f'{idx}'
                ip_ = '/'.join(['.'.join(ip), subnet])
            else:
                ip_ = f'172.16.111.{idx}/16'
            # add tap for this host
            logger.log('DEBUG', f"Creating host tap on {host}")
            kwargs = {'experiment'   : self.exp_name,
                      'command_type' : 'tap',
                      'computes'     : host,
                      'command'      : (f'create {mgmt_vlan} bridge phenix'
                                        f' ip {ip_} {self.tap}'),
                      'ignore_error' : True
            }
            mm.compute_cmd(**kwargs)
            if self.namespace:
                logger.log('DEBUG', f"Creating netns {self.ns} on {host}")
                # create network namespace
                cmd = f'ip netns add {self.ns}'
                mm.compute_cmd(experiment=self.exp_name, computes=host,
                               command=cmd)
                # move tap to namespace (clears IP)
                cmd = f'ip link set dev {self.tap} netns {self.ns}'
                mm.compute_cmd(experiment=self.exp_name, computes=host,
                               command=cmd)
                # assign IP address to the tap
                cmd = (f'ip netns exec {self.ns} ip'
                       f' addr add {ip_} dev {self.tap}')
                mm.compute_cmd(experiment=self.exp_name, computes=host,
                               command=cmd)
                # activate the network connection
                cmd = (f'ip netns exec {self.ns} ip'
                       f' link set dev {self.tap} up')
                mm.compute_cmd(experiment=self.exp_name, computes=host,
                               command=cmd)
        logger.log('INFO', f"Completed post_start for user application: {self.name}")

    def cleanup(self):
        logger.log('INFO', f"Running cleanup for user application: {self.name}")
        # remove management network tap
        for idx, host in enumerate(self.hosts, start=1):
            kwargs = {'experiment'   : self.exp_name,
                      'command_type' : 'tap',
                      'computes'     : host,
                      'command'      : f'delete {self.tap}',
                      'ignore_error' : True
            }
            mm.compute_cmd(**kwargs)
            if self.namespace:
                # remove the network namespace
                cmd = f"ip netns delete {self.ns}"
                mm.compute_cmd(experiment=self.exp_name, computes=host,
                               command=cmd)
        logger.log('INFO', f"Completed cleanup for user application: {self.name}")


def main():
    MgmtTap()
