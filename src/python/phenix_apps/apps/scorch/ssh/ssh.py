"""
Scorch component to execute commands on a remote host and copy files from a remote host.

Contributors: Klaehn Burkes, cmulk, and some AI friends.
"""

import json
import stat
from pathlib import Path, PurePath, PurePosixPath
from typing import Annotated, Final

import paramiko
from pydantic import (
    AfterValidator,
    Field,
    IPvAnyAddress,
    StringConstraints,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import FilePath, MetadataBlock, Seconds
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# Linux user names are limited to 32 characters by useradd (shadow-utils).
MAX_USER_LENGTH: Final[int] = 32

# paramiko cannot be told "no timeout" for the banner and login (None keeps its
# 15 and 30 second defaults), so 0 becomes a timeout nobody will reach.
# ponytail: ~68 years; a custom Transport would allow a true None
NO_TIMEOUT: Final[float] = 2**31


def _check_remote_path(value: str) -> str:
    # Remote paths are POSIX paths, whatever system phenix runs on.
    path = PurePosixPath(value)
    if not path.name or path.name == "..":
        raise ValueError("path must name a file or directory, not '/' or end in '..'")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RemotePath = Annotated[
    FilePath,
    StringConstraints(strip_whitespace=True),
    AfterValidator(_check_remote_path),
]


class SSHMetadata(MetadataBlock):
    """Metadata for the ssh component; see README.md for each field."""

    ip: IPvAnyAddress
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    user: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_USER_LENGTH
        ),
    ]
    password: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    ) = None
    # a known_hosts file; without it the server's host key is trusted blindly
    known_hosts: Text | None = None
    connect_timeout: Seconds = 10
    banner_timeout: Seconds = 0
    login_timeout: Seconds = 0
    cmds: Annotated[list[Text], Field(min_length=1)]
    files: list[RemotePath] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_file_names(self):
        # each file lands in <stage>/<last path component>
        seen: set[str] = set()
        for file in self.files:
            name = PurePosixPath(file).name
            if name in seen:
                raise ValueError(
                    f"files: more than one entry ends in '{name}'; "
                    "they would overwrite each other"
                )
            seen.add(name)
        return self


class SSH(ComponentBase):
    """
    Sets up ssh connection between phenix server and a remote collection server as a Scorch component.
    """

    metadata_model = SSHMetadata
    config: SSHMetadata

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

        self._log(
            f"{stage}_remote",
            f"{stage.capitalize()} SSH on remote server {self.config.ip} "
            f"with user {self.config.user}.",
            host=str(self.config.ip),
            user=self.config.user,
        )

        ssh = None
        try:
            ssh = self._connect()

            remote_cmd = " && ".join(self.config.cmds)
            self._log(f"{stage}_remote", "Running Remotely", cmd=remote_cmd)
            cmd_out = self._run_remote_command(ssh, remote_cmd)
            self._log(f"{stage}_remote", **cmd_out)

            if self.config.files:
                sftp_path = self.base_dir / stage
                for remote_file in self.config.files:
                    local_path = str(sftp_path / PurePath(remote_file).name)
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

        if self.config.known_hosts:
            ssh.load_host_keys(self.config.known_hosts)
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            logger.warning(
                f"no 'known_hosts' file provided in metadata; automatically "
                f"trusting host key presented by {self.config.ip}"
            )
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": str(self.config.ip),
            "port": self.config.port,
            "username": self.config.user,
            # 0 means no timeout
            "timeout": self.config.connect_timeout or None,
            "banner_timeout": self.config.banner_timeout or NO_TIMEOUT,
            "auth_timeout": self.config.login_timeout or NO_TIMEOUT,
        }

        if self.config.password:
            connect_kwargs["password"] = self.config.password

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
            # after reading, so a chatty command cannot fill the window and hang;
            # paramiko reports -1 when the server sends no status
            exit_status: int | None
            try:
                exit_status = stdout.channel.recv_exit_status()
            except Exception as ex:
                logger.warning(
                    f"no exit status for remote command on {self.config.ip}: {ex}"
                )
                exit_status = None

            # a failing command has never failed the stage; say so loudly
            if exit_status != 0:
                logger.warning(
                    f"remote command exited with status {exit_status} on "
                    f"{self.config.ip}: {command}"
                )

            return {
                "host": str(self.config.ip),
                "cmd": command,
                "exit_status": exit_status,
                "stdout": output,
                "stderr": error,
            }

        except Exception as e:
            logger.error(f"Failed to execute remote command: {command}. Error: {e}")
            return {
                "host": str(self.config.ip),
                "cmd": command,
                "exit_status": None,
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
            "host": str(self.config.ip),
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
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
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
        Path(local_dir).mkdir(parents=True, exist_ok=True)

        for entry in sftp.listdir_attr(remote_dir):
            name = entry.filename
            if not name or name in (".", "..") or "/" in name:
                logger.error(
                    f"skipping remote entry with unsafe filename '{name}' in '{remote_dir}'"
                )
                continue

            remote_path = f"{remote_dir.rstrip('/')}/{name}"
            local_path = str(utils.safe_join(local_dir, name))

            if stat.S_ISDIR(entry.st_mode):
                self._sftp_get_dir(sftp, remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

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
