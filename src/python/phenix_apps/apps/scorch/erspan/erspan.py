"""
Scorch component to set up network traffic mirroring from a phenix experiment (openvswitch bridge) to a remote capture host via ERSPAN.
Optionally, it can connect to the remote host and autoconfigure the receiver.

Contributors: Klaehn Burkes, cmulk, and some AI friends.
"""

import json
from pathlib import Path

import paramiko

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class ERSPAN(ComponentBase):
    """
    Sets up an ERSPAN tunnel on the local phenix server and, optionally,
    configures the remote collection server (receiver) via SSH.
    """

    def __init__(self):
        ComponentBase.__init__(self, "erspan")
        self.erspan_metadata = []
        self.execute_stage()

    def configure(self):
        """
        Configures the ERSPAN session and mirror port on the local server.
        If remote_config is provided, also configures the remote receiver via SSH.
        """
        self._log("config_component", f"Configuring user component: {self.name}")

        self._get_args()

        vlan_ids = self._get_mirrored_vlans()

        self._log("config_component", f"Excluded VLANs: {self.excluded_vlans}")

        logger.info("Configuring ERSPAN on local server.")

        # Cmd to set up open vswitch bridge and interface in erspan mode
        cmd_1 = f"ovs-vsctl add-port {self.local_bridge} {self.local_interface} -- set interface {self.local_interface} type=erspan options:remote_ip={self.remote_ip} options:key={self.session_key} options:erspan_ver=1"
        # Cmd to configure the mirror to send only the non-excluded ports to the interface
        cmd_2 = self._configure_mirror(
            vlan_ids, self.local_bridge, "m0", self.local_interface
        )

        cmd_out = self._run_mm(cmd_1)
        self._log("config_local", "Running Locally", **cmd_out)

        cmd_out = self._run_mm(cmd_2)
        self._log("config_local", "Running Locally", **cmd_out)

        if self.remote_config:
            rc = self.remote_config

            self._log(
                "config_remote",
                f"Configuring ERSPAN on remote server {rc.ssh_ip} with user {rc.user}.",
                host=rc.ssh_ip,
                user=rc.user,
            )

            # If no remote_bridge is provided, only configure the erspan interface
            cmd_list = [
                f"sudo ip link add {rc.remote_interface} type erspan local {self.remote_ip} remote {self.local_ip} erspan_ver 0 key {self.session_key}",
                f"sudo ip link set dev {rc.remote_interface} up",
            ]

            # If a remote_bridge is provided, add the erspan interface to the bridge and configure it to flood traffic to all ports
            if rc.get("remote_bridge") is not None:
                cmd_list.extend(
                    [
                        f"sudo ovs-vsctl add-port {rc.remote_bridge} {rc.remote_interface}",
                        f'sudo ovs-ofctl add-flow {rc.remote_bridge} "priority=100,in_port={rc.remote_interface},actions=FLOOD"',
                        # Make sure the erspan interface does not receive flooded traffic from other ports on the bridge
                        f"sudo ovs-ofctl mod-port {rc.remote_bridge} {rc.remote_interface} no-flood",
                    ]
                )

            remote_cmd = " && ".join(cmd_list)
            self._run_remote_command(remote_cmd, "config_remote")
        else:
            logger.info("No remote_config provided — skipping remote receiver setup.")

        self._log("config_component", f"Configured user component: {self.name}")

        # Save Logs to JSON file
        m_path = Path(self.base_dir, "erspan_metadata_configure.json")
        logger.info(f"Saving ERSPAN metadata to {m_path}")
        utils.write_json(m_path, self.erspan_metadata)

    def cleanup(self):
        self._log("cleanup_component", f"Cleaning up user component: {self.name}")

        self._get_args()

        logger.info("Cleaning up erspan on local server")

        cmd_1 = f"ovs-vsctl clear bridge {self.local_bridge} mirrors"
        cmd_2 = f"ovs-vsctl del-port {self.local_bridge} {self.local_interface}"

        cmd_out = self._run_mm(cmd_1)
        self._log("cleanup_local", "Running Locally", **cmd_out)
        cmd_out = self._run_mm(cmd_2)
        self._log("cleanup_local", "Running Locally", **cmd_out)

        if self.remote_config:
            rc = self.remote_config

            self._log(
                "cleanup_remote",
                f"Cleaning up ERSPAN on remote server {rc.ssh_ip} with user {rc.user}.",
                host=rc.ssh_ip,
                user=rc.user,
            )

            cmd_list = []
            if rc.get("remote_bridge") is not None:
                cmd_list.extend(
                    [
                        f'sudo ovs-ofctl del-flows {rc.remote_bridge} "in_port={rc.remote_interface}"',
                        f"sudo ovs-vsctl del-port {rc.remote_bridge} {rc.remote_interface}",
                    ]
                )
            cmd_list.append(f"sudo ip link del dev {rc.remote_interface}")

            remote_cmd = " ; ".join(cmd_list)
            self._run_remote_command(remote_cmd, "cleanup_remote")
        else:
            logger.info("No remote_config provided — skipping remote cleanup.")

        # Save Logs to JSON file
        m_path = Path(self.base_dir, "erspan_metadata_cleanup.json")
        logger.info(f"Saving ERSPAN metadata to {m_path}")
        utils.write_json(m_path, self.erspan_metadata)

        logger.info(f"Stopped user component: {self.name}")

    def _run_mm(self, command):
        """
        Helper to run a command in the minimega container (like ovs commands for example)
        """
        try:
            res = self.mm.shell(command)
            return {
                "host": res[0].get("Host", ""),
                "cmd": command,
                "stdout": list(res[0].get("Response", "").splitlines()),
                "stderr": list(res[0].get("Error", "").splitlines()),
            }
        except Exception as e:
            logger.error(f"Failed to execute local command: {command}. Error: {e}")
            return {
                "host": "local",
                "cmd": command,
                "stderr": str(e),
            }

    def _run_remote_command(self, command, event_type="remote"):
        """
        Runs a shell command on a remote server using SSH.
        Only called when self.remote_config is present.

        Args:
            command (str): The command to run.
            event_type (str): The event type for logging (e.g. "config_remote", "cleanup_remote").

        Raises:
            RuntimeError: If the remote command returns a non-zero exit status.
        """
        rc = self.remote_config

        try:
            # Initialize SSH connection using paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": rc.ssh_ip,
                "port": 22,
                "username": rc.user,
            }

            if rc.get("password"):
                connect_kwargs["password"] = rc.password

            ssh.connect(**connect_kwargs)

            # Execute the command
            _stdin, stdout, stderr = ssh.exec_command(command)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            exit_status = stdout.channel.recv_exit_status()
            ssh.close()

            result = {
                "host": rc.ssh_ip,
                "cmd": command,
                "stdout": output,
                "stderr": error,
            }

            self._log(event_type, "Running Remotely", **result)

            if exit_status != 0:
                raise RuntimeError(
                    f"Remote command failed (exit code {exit_status}): {result.get('stderr', '')}"
                )
        except Exception as e:
            logger.error(e)
            raise

    def _get_args(self):
        """
        Parse and validate component metadata.

        Top-level required: local_bridge, local_ip, remote_ip
        Top-level optional: local_interface (default "erspan1"), session_key (default 100)
        Optional section:   remote_config (object) — when present, remote_bridge, ssh_ip,
                            and user are required; remote_interface (default "erspan1")
                            and password are optional.
        """
        # --- Top-level required ---
        self.local_bridge = self.metadata.get("local_bridge")
        if self.local_bridge is None:
            raise ValueError("No 'local_bridge' provided in metadata")

        self.local_ip = self.metadata.get("local_ip")
        if self.local_ip is None:
            raise ValueError("No 'local_ip' provided in metadata")

        self.remote_ip = self.metadata.get("remote_ip")
        if self.remote_ip is None:
            raise ValueError("No 'remote_ip' provided in metadata")

        # --- Top-level optional with defaults ---
        self.local_interface = self.metadata.get("local_interface", "erspan1")
        self.session_key = self.metadata.get("session_key", 100)
        self.excluded_vlans = self.metadata.get("excluded_vlans", [])
        if isinstance(self.excluded_vlans, str):
            self.excluded_vlans = [self.excluded_vlans]

        # --- Optional remote_config section ---
        self.remote_config = self.metadata.get("remote_config")

        if self.remote_config:
            rc = self.remote_config

            if not rc.get("ssh_ip"):
                raise ValueError("No 'ssh_ip' provided in remote_config")
            if not rc.get("user"):
                raise ValueError("No 'user' provided in remote_config")

            # Apply default for optional remote fields
            if not rc.get("remote_interface"):
                rc.remote_interface = "erspan1"

    def _get_mirrored_vlans(self) -> list[int]:
        """
        Return a sorted list of unique VLAN IDs (integers) for all VLANs that
        are not in ``self.excluded_vlans``, collected from experiment status.
        """
        included_vlans: set[int] = set()
        excluded_lower = {v.strip().lower() for v in self.excluded_vlans}

        for alias, vlan_id in self.experiment.status.vlans.items():
            if alias.strip().lower() not in excluded_lower and vlan_id is not None:
                included_vlans.add(int(vlan_id))

        return sorted(included_vlans)

    def _configure_mirror(
        self, vlan_ids: list[int], bridge_name, mirror_name, output_port
    ):
        """
        Build an ``ovs-vsctl`` command that creates a mirror which selects all
        traffic on the given VLAN IDs and outputs it to ``output_port``.
        """
        select_vlan = ",".join(str(v) for v in vlan_ids)

        return (
            f"ovs-vsctl "
            f"-- --id=@p get Port {output_port} "
            f"-- --id=@m create Mirror name={mirror_name} "
            f"select_all=true select_vlan={select_vlan} output-port=@p "
            f"-- set Bridge {bridge_name} mirrors=@m"
        )

    def _log(self, event_type: str, message: str | None = None, **data) -> None:
        """
        Store structured ERSPAN-related metadata and print a human-readable message.
        """
        entry = {
            "event": event_type,
            "message": message,
            "data": data,
        }
        # store for later JSON dump
        self.erspan_metadata.append(entry)

        logger.info(json.dumps(entry))


def main():
    ERSPAN()


if __name__ == "__main__":
    main()
