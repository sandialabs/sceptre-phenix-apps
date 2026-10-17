# SSH Component

Scorch component to execute commands on a remote host and copy files from a
remote host.

```
type:   ssh
exe:    phenix-scorch-component-ssh
stages: configure, start, stop, cleanup
```

Every stage it is listed in does the same thing: run all of `cmds` (joined with
` && `, so the first failure stops the rest), fetch `files`. For different jobs
at different points, define one `ssh` component per job (second example).

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
<stage>/                    each entry of files, by its last path component
ssh_metadata_<stage>.json   what this stage did, step by step
<stage>-<UTC time>.json     the SCORCH status file (logs, and the error on failure)
```

Each entry of `ssh_metadata_<stage>.json` has an `event`, a `message` and `data`:

```json
{
  "event": "start_remote",
  "message": null,
  "data": {
    "host": "192.168.1.4",
    "cmd": "uptime",
    "exit_status": 0,
    "stdout": "up 3 days",
    "stderr": ""
  }
}
```

## Before you start

- The server must be reachable over SSH from where phenix runs (inside the
  phenix container, if phenix runs in one).
- Login uses SSH agent keys or `~/.ssh/id_*`, or `password` (which also unlocks an encrypted key).

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `ip` | IP address | yes | | Address of the server |
| `port` | integer, 1-65535 | no | `22` | SSH port |
| `user` | string, 1-32 characters | yes | | User to log in as |
| `password` | string | no | | Password for `user`. Without it, SSH keys are used |
| `connect_timeout` | seconds | no | `10` | Time to wait for the TCP connection; `0` waits forever |
| `banner_timeout` | seconds | no | `0` | Time to wait for the server's SSH banner; `0` waits forever |
| `login_timeout` | seconds | no | `0` | Time to wait for authentication; `0` waits forever |
| `cmds` | list of strings | yes | | Commands to run, in order. At least one |
| `files` | list of paths | no | none | Remote files or directories (copied recursively) to fetch after the commands run. No spaces or shell characters; no two may end in the same name |

## Examples

Collect a server's logs once, at the end of the run, with key-based login.

```yaml
components:
  - name: collect-logs
    type: ssh
    metadata:
      ip: 192.168.1.4
      user: ubuntu
      cmds:
        - tar czf /tmp/app-logs.tgz -C /var/log app
      files:
        - /tmp/app-logs.tgz
runs:
  - configure: []
    start: []
    stop: [collect-logs]
    cleanup: []
```

Start a recorder when the run starts, stop it and fetch its output when the
run stops.

```yaml
components:
  - name: recorder-start
    type: ssh
    metadata:
      ip: 192.168.1.5
      user: phenix
      password: "s3cret"
      cmds:
        - rm -rf /data/run
        - mkdir -p /data/run
        # in a subshell with every stream redirected, or the stage would wait
        # for the recorder to exit
        - (nohup recorder --out /data/run > /dev/null 2>&1 < /dev/null &)
  - name: recorder-stop
    type: ssh
    metadata:
      ip: 192.168.1.5
      user: phenix
      password: "s3cret"
      cmds:
        - pkill -INT recorder
      files:
        - /data/run
runs:
  - configure: []
    start: [recorder-start]
    stop: [recorder-stop]
    cleanup: []
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `ip: value is not a valid IPv4 or IPv6 address` | `ip` is a hostname or malformed. Use the server's IP address. |
| `files: Value error, files: more than one entry ends in '<name>'` | Two `files` entries would be saved to the same place. Rename one on the remote host. |
| `[Errno None] Unable to connect to port 22 on <address>` | The host refused the connection or is unreachable from where phenix runs. |
| `Authentication failed.` | Wrong `password`, or every key offered was rejected. |
| `Private key file is encrypted` | The default key file needs a passphrase. Set `password` to it, or use an agent. |
| the stage never finishes after starting something in the background | The job holds the session open. Redirect stdout, stderr and stdin and wrap it in a subshell, as in the second example. |
| warning `remote command exited with status <N> on <ip>: <cmd>` | One of `cmds` failed; later ones did not run. See `stderr` in `ssh_metadata_<stage>.json`. |

## Limitations

- `banner_timeout` and `login_timeout` default to waiting forever.
- Host keys are not verified: only use this on a network you trust.
- `~/.ssh/config` is not read, and `password` is stored in plain text in the
  scenario.
- A failing command or a failed fetch is recorded but does not fail the stage.
- Commands are recorded in `ssh_metadata_<stage>.json`, so keep secrets out of
  `cmds`. They are not syntax-checked before they run.
