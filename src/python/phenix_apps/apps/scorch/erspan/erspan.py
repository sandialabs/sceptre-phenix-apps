"""
Scorch component to set up network traffic mirroring from a phenix experiment (openvswitch bridge) to a remote capture host via ERSPAN.
Optionally, it can connect to the remote host and autoconfigure the receiver.

Contributors: Klaehn Burkes, cmulk, and some AI friends.
"""

import json
from pathlib import Path
from typing import Annotated, Any

import paramiko
from pydantic import (
    AfterValidator,
    Field,
    IPvAnyAddress,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import Interface, MetadataBlock, PositiveSeconds
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _no_scope(ip: IPvAnyAddress) -> IPvAnyAddress:
    # An IPv6 scope ("fe80::1%eth0") is free text that ends up in shell commands.
    if getattr(ip, "scope_id", None):
        raise ValueError("scoped IPv6 addresses (with %) are not supported")
    return ip


Address = Annotated[IPvAnyAddress, AfterValidator(_no_scope)]


class RemoteConfig(MetadataBlock):
    ssh_ip: Address
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    # Linux user names are limited to 32 characters by useradd (shadow-utils).
    user: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
    ]
    password: Annotated[str, Field(min_length=1)] | None = None
    remote_bridge: Interface | None = None
    remote_interface: Interface = "erspan1"
    # None keeps paramiko's default: no timeout.
    ssh_timeout: PositiveSeconds | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_remote_interface(cls, data: Any) -> Any:
        # an empty remote_interface means the default, as it always has
        if isinstance(data, dict) and data.get("remote_interface") == "":
            data = {k: v for k, v in data.items() if k != "remote_interface"}
        return data


class ERSPANMetadata(MetadataBlock):
    """Metadata for the erspan component; see README.md for each field."""

    local_bridge: Interface
    local_ip: Address
    remote_ip: Address
    local_interface: Interface = "erspan1"
    session_key: int = Field(default=100, ge=0, le=2**32 - 1, strict=True)
    excluded_vlans: list[Text] = Field(default_factory=list)
    remote_config: RemoteConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _compat(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # an empty remote_config block means "no remote side"
        if data.get("remote_config") == {}:
            data = {**data, "remote_config": None}
        # a single VLAN name may be given without a list
        if isinstance(data.get("excluded_vlans"), str):
            data = {**data, "excluded_vlans": [data["excluded_vlans"]]}
        return data


class ERSPAN(ComponentBase):
    """
    Sets up an ERSPAN tunnel on the local phenix server and, optionally,
    configures the remote collection server (receiver) via SSH.
    """

    metadata_model = ERSPANMetadata
    config: ERSPANMetadata

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

        vlan_ids = self._get_mirrored_vlans()

        self._log("config_component", f"Excluded VLANs: {self.config.excluded_vlans}")

        logger.info("Configuring ERSPAN on local server.")

        self._warn_about_other_mirrors()

        # Cmd to set up open vswitch bridge and interface in erspan mode
        cmd_1 = f"ovs-vsctl add-port {self.config.local_bridge} {self.config.local_interface} -- set interface {self.config.local_interface} type=erspan options:remote_ip={self.config.remote_ip} options:key={self.config.session_key} options:erspan_ver=1"
        # Cmd to configure the mirror to send only the non-excluded ports to the interface
        cmd_2 = self._configure_mirror(
            vlan_ids,
            self.config.local_bridge,
            self._mirror_name,
            self.config.local_interface,
        )

        cmd_out = self._run_mm(cmd_1)
        self._log("config_local", "Running Locally", **cmd_out)

        cmd_out = self._run_mm(cmd_2)
        self._log("config_local", "Running Locally", **cmd_out)

        if self.config.remote_config:
            rc = self.config.remote_config

            self._log(
                "config_remote",
                f"Configuring ERSPAN on remote server {rc.ssh_ip} with user {rc.user}.",
                host=str(rc.ssh_ip),
                user=rc.user,
            )

            # If no remote_bridge is provided, only configure the erspan interface
            cmd_list = [
                f"sudo ip link add {rc.remote_interface} type erspan local {self.config.remote_ip} remote {self.config.local_ip} erspan_ver 0 key {self.config.session_key}",
                f"sudo ip link set dev {rc.remote_interface} up",
            ]

            # If a remote_bridge is provided, add the erspan interface to the bridge and configure it to flood traffic to all ports
            if rc.remote_bridge is not None:
                cmd_list.extend(
                    [
                        f"sudo ovs-vsctl add-port {rc.remote_bridge} {rc.remote_interface}",
                        f'sudo ovs-ofctl add-flow {rc.remote_bridge} "priority=100,in_port={rc.remote_interface},actions=FLOOD"',
                        # Make sure the erspan interface does not receive flooded traffic from other ports on the bridge
                        f"sudo ovs-ofctl mod-port {rc.remote_bridge} {rc.remote_interface} no-flood",
                    ]
                )

            # the commands depend on each other: the first failure stops the rest
            self._run_remote_commands(cmd_list, "config_remote")
        else:
            logger.info("No remote_config provided — skipping remote receiver setup.")

        self._log("config_component", f"Configured user component: {self.name}")

        # Save Logs to JSON file
        m_path = Path(self.base_dir, "erspan_metadata_configure.json")
        logger.info(f"Saving ERSPAN metadata to {m_path}")
        utils.write_json(m_path, self.erspan_metadata)

    def cleanup(self):
        self._log("cleanup_component", f"Cleaning up user component: {self.name}")

        logger.info("Cleaning up erspan on local server")

        # only this component's mirror: others on the bridge are left alone
        cmd_1 = (
            f"ovs-vsctl -- --id=@m get Mirror {self._mirror_name} "
            f"-- remove Bridge {self.config.local_bridge} mirrors @m"
        )
        cmd_2 = f"ovs-vsctl del-port {self.config.local_bridge} {self.config.local_interface}"

        cmd_out = self._run_mm(cmd_1)
        self._log("cleanup_local", "Running Locally", **cmd_out)
        cmd_out = self._run_mm(cmd_2)
        self._log("cleanup_local", "Running Locally", **cmd_out)

        if self.config.remote_config:
            rc = self.config.remote_config

            self._log(
                "cleanup_remote",
                f"Cleaning up ERSPAN on remote server {rc.ssh_ip} with user {rc.user}.",
                host=str(rc.ssh_ip),
                user=rc.user,
            )

            cmd_list = []
            if rc.remote_bridge is not None:
                cmd_list.extend(
                    [
                        f'sudo ovs-ofctl del-flows {rc.remote_bridge} "in_port={rc.remote_interface}"',
                        f"sudo ovs-vsctl del-port {rc.remote_bridge} {rc.remote_interface}",
                    ]
                )
            cmd_list.append(f"sudo ip link del dev {rc.remote_interface}")

            # independent: try them all, then report every failure
            self._run_remote_commands(cmd_list, "cleanup_remote", keep_going=True)
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

    def _run_remote_commands(
        self, commands: list[str], event_type: str, keep_going: bool = False
    ) -> None:
        """
        Runs shell commands on a remote server over one SSH connection.
        Only called when self.config.remote_config is present.

        Args:
            commands: The commands to run, in order.
            event_type: The event type for logging (e.g. "config_remote").
            keep_going: Run the rest after a failure instead of stopping.

        Raises:
            RuntimeError: If any command returns a non-zero exit status.
        """
        rc = self.config.remote_config
        assert rc is not None
        failures: list[str] = []

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            connect_kwargs: dict[str, Any] = {
                "hostname": str(rc.ssh_ip),
                "port": rc.port,
                "username": rc.user,
            }

            if rc.password:
                connect_kwargs["password"] = rc.password

            if rc.ssh_timeout is not None:
                connect_kwargs["timeout"] = rc.ssh_timeout
                connect_kwargs["banner_timeout"] = rc.ssh_timeout
                connect_kwargs["auth_timeout"] = rc.ssh_timeout

            ssh.connect(**connect_kwargs)

            for command in commands:
                _stdin, stdout, stderr = ssh.exec_command(
                    command, timeout=rc.ssh_timeout
                )
                output = stdout.read().decode().strip()
                error = stderr.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()

                self._log(
                    event_type,
                    "Running Remotely",
                    host=str(rc.ssh_ip),
                    cmd=command,
                    stdout=output,
                    stderr=error,
                )

                if exit_status != 0:
                    failure = (
                        f"Remote command failed (exit code {exit_status}): {error}"
                    )
                    logger.error(failure)
                    failures.append(failure)
                    if not keep_going:
                        break
        except Exception as e:
            logger.error(e)
            raise
        finally:
            ssh.close()

        if failures:
            raise RuntimeError("; ".join(failures))

    @property
    def _mirror_name(self) -> str:
        """Names this component's mirror, so cleanup removes only that one."""
        return f"scorch-{self.config.local_interface}"

    def _warn_about_other_mirrors(self) -> None:
        """Warn if the bridge already has mirrors: they are not ours to remove."""
        out = self._run_mm(f"ovs-vsctl get Bridge {self.config.local_bridge} mirrors")
        existing = " ".join(out.get("stdout", [])).strip()
        if existing not in ("", "[]"):
            logger.warning(
                f"bridge {self.config.local_bridge} already has mirrors {existing}; "
                f"they are left as they are and may duplicate or conflict with "
                f"{self._mirror_name}"
            )

    def _get_mirrored_vlans(self) -> list[int]:
        """
        Return a sorted list of unique VLAN IDs (integers) for all VLANs that
        are not in ``self.config.excluded_vlans``, collected from experiment status.
        """
        included_vlans: set[int] = set()
        excluded_lower = {v.strip().lower() for v in self.config.excluded_vlans}
        vlans = self.experiment.status.vlans or {}

        known = {alias.strip().lower() for alias in vlans}
        if unknown := sorted(excluded_lower - known):
            logger.warning(
                f"excluded_vlans names VLANs this experiment does not have, so "
                f"they exclude nothing: {', '.join(unknown)} (known: "
                f"{', '.join(sorted(known)) or 'none'})"
            )

        for alias, vlan_id in vlans.items():
            if alias.strip().lower() not in excluded_lower and vlan_id is not None:
                included_vlans.add(int(vlan_id))

        # An empty select_vlan makes OVS mirror every VLAN, the opposite of
        # what excluding them all asks for.
        if not included_vlans:
            raise ValueError(
                "no VLANs left to mirror: the experiment has no VLANs, or "
                "excluded_vlans names all of them"
            )

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
            f"-- add Bridge {bridge_name} mirrors @m"
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
