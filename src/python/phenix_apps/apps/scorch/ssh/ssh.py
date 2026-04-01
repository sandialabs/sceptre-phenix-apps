"""
Scorch component to execute commands on a remote host and copy files from a remote host.

Contributors: Klaehn Burkes, cmulk, and some AI friends.
"""

import json
import os
import stat
from pathlib import Path

import paramiko

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class SSH(ComponentBase):
    """
    Sets up ssh connection between phenix server and a remote collection server as a Scorch component.
    """

    def __init__(self):
        ComponentBase.__init__(self, "ssh")
        self.ssh_metadata = []
        self.execute_stage()

    def configure(self):
        """
        Configures the SSH connection and executes remote commands during the configuration stage.

        Establishes an SSH connection to the remote server, runs the specified commands,
        and optionally fetches remote files to the local system. Logs all operations
        and saves metadata to a JSON file.
        """
        self._run("configure")

    def cleanup(self):
        """
        Executes cleanup operations by running SSH commands and fetching files during the cleanup stage.

        Establishes an SSH connection to the remote server, runs the specified cleanup commands,
        and optionally fetches remote files to the local system. Logs all cleanup operations
        and saves metadata to a JSON file.
        """
        self._run("cleanup")

    def start(self):
        """
        Executes start operations by running SSH commands and fetching files during the start stage.

        Establishes an SSH connection to the remote server, runs the specified start commands,
        and optionally fetches remote files to the local system. Logs all start operations
        and saves metadata to a JSON file.
        """
        self._run("start")

    def stop(self):
        """
        Executes stop operations by running SSH commands and fetching files during the stop stage.

        Establishes an SSH connection to the remote server, runs the specified stop commands,
        and optionally fetches remote files to the local system. Logs all stop operations
        and saves metadata to a JSON file.
        """
        self._run("stop")

    def _run(self, stage: str):
        """
        Shared implementation for configure, cleanup, start, and stop stages.

        Args:
            stage (str): The operation stage - "configure", "cleanup", "start", or "stop".
        """
        self._log(
            f"{stage}_component", f"{stage.capitalize()} user component: {self.name}"
        )

        self._get_args()

        self._log(
            f"{stage}_remote",
            f"{stage.capitalize()} SSH on remote server {self.ip} with user {self.user}.",
            host=self.ip,
            user=self.user,
        )

        ssh = None
        try:
            ssh = self._connect()

            remote_cmd = " && ".join(self.cmds)
            self._log(f"{stage}_remote", "Running Remotely", cmd=remote_cmd)
            cmd_out = self._run_remote_command(ssh, remote_cmd)
            self._log(f"{stage}_remote", **cmd_out)

            if self.files:
                sftp_path = self.base_dir + f"/{stage}/"
                for remote_file in self.files:
                    local_path = os.path.join(sftp_path, os.path.basename(remote_file))
                    files_out = self._fetch_remote(ssh, remote_file, local_path)
                    self._log(
                        f"{stage}_remote",
                        f"Pulling Remotely and saving to {local_path}",
                        **files_out,
                    )
                    if files_out.get("status", "") == "error":
                        logger.error(files_out.get("error", ""))
        except Exception as e:
            logger.error(e)
            raise
        finally:
            if ssh is not None:
                ssh.close()
        self._log(
            f"{stage}_component", f"{stage.capitalize()} user component: {self.name}"
        )

        # Save Logs to JSON file
        m_path = Path(self.base_dir, f"ssh_metadata_{stage}.json")
        logger.info(f"Saving SSH metadata to {m_path}")
        utils.write_json(m_path, self.ssh_metadata)

    def _connect(self) -> paramiko.SSHClient:
        """
        Establish and return a new SSH connection to the remote host.

        Returns:
            paramiko.SSHClient: An open, authenticated SSH client.

        Raises:
            paramiko.SSHException: If the connection or authentication fails.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.ip,
            "port": 22,
            "username": self.user,
        }

        if self.password:
            connect_kwargs["password"] = self.password

        ssh.connect(**connect_kwargs)
        return ssh

    def _run_remote_command(self, ssh: paramiko.SSHClient, command: str) -> dict:
        """
        Runs a shell command on the remote server using an existing SSH connection.

        Args:
            ssh (paramiko.SSHClient): An open SSH connection.
            command (str): The command to run.

        Returns:
            {
                "host": <remote host>,
                "cmd": "<command run>",
                "stdout": "<output from run if any>",
                "stderr": "<error message if any>",
            }
        """
        try:
            _stdin, stdout, stderr = ssh.exec_command(command)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

            return {
                "host": self.ip,
                "cmd": command,
                "stdout": output,
                "stderr": error,
            }

        except Exception as e:
            logger.error(f"Failed to execute remote command: {command}. Error: {e}")
            return {
                "host": self.ip,
                "cmd": command,
                "stdout": "",
                "stderr": str(e),
            }

    def _fetch_remote(
        self, ssh: paramiko.SSHClient, remote_path: str, local_path: str
    ) -> dict:
        """
        Fetch a file or directory from the remote host using SFTP.

        - If remote_path is a file: download it to local_path.
        - If remote_path is a directory: recursively download into local_path.

        Args:
            ssh (paramiko.SSHClient): An open SSH connection.
            remote_path (str): Path on the remote host to fetch.
            local_path (str): Local destination path (file or directory).

        Returns:
            {
                "host": <remote host>,
                "src": <remote_path>,
                "dst": <local_path>,
                "status": "ok" | "error",
                "error": "<error message if any>",
            }
        """
        result = {
            "host": self.ip,
            "src": remote_path,
            "dst": local_path,
            "status": "ok",
            "error": "",
        }

        sftp = None
        try:
            sftp = ssh.open_sftp()

            rstat = sftp.stat(remote_path)
            if stat.S_ISDIR(rstat.st_mode):
                self._sftp_get_dir(sftp, remote_path, local_path)
            else:
                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                sftp.get(remote_path, local_path)

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        finally:
            if sftp is not None:
                sftp.close()

        return result

    def _sftp_get_dir(
        self, sftp: paramiko.SFTPClient, remote_dir: str, local_dir: str
    ) -> None:
        """
        Recursively download a remote directory to a local directory using an already-open SFTP client.

        Creates the local directory structure and downloads all files and subdirectories
        from the remote directory to the corresponding local directory.

        Args:
            sftp (paramiko.SFTPClient): An open SFTP client connection.
            remote_dir (str): Path to the remote directory to download.
            local_dir (str): Local destination directory path.
        """
        os.makedirs(local_dir, exist_ok=True)

        for entry in sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir.rstrip('/')}/{entry.filename}"
            local_path = os.path.join(local_dir, entry.filename)

            if stat.S_ISDIR(entry.st_mode):
                self._sftp_get_dir(sftp, remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

    def _get_args(self):
        """
        Parses and validates metadata fields required for SSH operations,
        setting instance attributes for ip, user, password, cmds, and files.

        Raises:
            ValueError: If ip, user, or cmds are missing from metadata.
        """
        self.ip = self.metadata.get("ip")
        if self.ip is None:
            logger.error("No IP Provided")
            raise ValueError("No IP Provided")
        self.user = self.metadata.get("user")
        if self.user is None:
            logger.error("No User Provided")
            raise ValueError("No User Provided")
        self.password = self.metadata.get("password")
        self.cmds = self.metadata.get("cmds")
        if self.cmds is None:
            logger.error("No Command Provided")
            raise ValueError("No Command Provided")
        self.files = self.metadata.get("files")

    def _log(self, event_type: str, message: str | None = None, **data) -> None:
        """
        Store structured SSH-related metadata and log to phenix.

        Logs SSH operations with event type, message, and additional data. Stores
        the log entry in the ssh_metadata list and prints formatted output to
        the console.

        Args:
            event_type (str): Type of event being logged (e.g., 'config_component', 'cleanup_remote').
            message (str | None): Human-readable message to display.
            **data: Additional key-value pairs to include in the log entry.
        """
        entry = {
            "event": event_type,
            "message": message,
            "data": data,
        }
        self.ssh_metadata.append(entry)

        logger.info(json.dumps(entry))


def main():
    SSH()


if __name__ == "__main__":
    main()
