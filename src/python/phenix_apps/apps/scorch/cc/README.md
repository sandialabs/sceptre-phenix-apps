# minimega Command and Control (cc) Component

Runs commands and moves files on experiment VMs through minimega's `cc`
(miniccc) channel, at chosen points of a SCORCH run. Use it to start a service,
run a check and fail the run if it does not pass, background a long-running
process, or copy a file onto or off a VM.

```
type:   cc
exe:    phenix-scorch-component-cc
stages: configure, start, stop, cleanup
```

> NOTE: miniccc must be installed and running on the target VM(s).

In each stage the component runs that stage's top-level (stage-level) commands,
in order, then each `vms` entry's commands for that stage, in order.

There are two separate command vocabularies: **stage-level** commands run
against a `cc` filter (or every connected VM), while **VM-level** commands run
against the one VM whose `hostname` they name.

## Metadata

Top level:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `configure`, `start`, `stop`, `cleanup` | list of stage-level commands | none | Stage-level commands for that stage |
| `vms` | list | none | VMs with their own VM-level commands |

A stage-level command:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | `reset` or `exec` | yes | |
| `args` | string | for `exec` | Command handed to `cc exec`, read by minimega's lexer (see the Notes) |
| `filter` | string | no | A `cc` filter applied before the command (`tag=foo:bar`); same lexer rules as `args` |
| `once` | bool | no (`true`) | Run the command only once (see the Notes) |

A `vms` entry:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `hostname` | topology node name | yes | VM in the experiment |
| `configure`, `start`, `stop`, `cleanup` | list of VM-level commands | no | Commands for that stage |

A VM-level command:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | `exec`, `background`, `send`, `recv` or `reset` | yes | |
| `args` | string | for `exec`, `background`, `send`, `recv` | A command (`exec`/`background`), or a file path (`send`/`recv`, as `src` or `src:dst`) |
| `once` | bool | no (`true`) | For `exec`/`background`: run the command only once |
| `wait` | bool | no (`false`) | For `exec`: wait for the command to finish and fail the stage on a non-zero exit |
| `validator` | string (bash) | no | For `exec`: a script that checks the command's output; forces `wait` |

## Types

- Stage-level command types
  - `reset`: reset miniccc state, by clearing the filter and deleting all
    commands and responses. **WARNING**: THIS WILL INTERFERE WITH OPERATION OF
    MANY COMPONENTS! Reset should only be used at the start or end of a run or a
    loop (use with special care in loops!).
  - `exec`: execute a command (`cc exec`), against the optional `filter`.
- VM-level command types
  - `exec`: execute a command (`cc exec`) on the VM.
  - `background`: execute a command in the background (the component continues).
  - `send`: send a file (host -> VM).
  - `recv`: receive a file (VM -> host).
  - `reset`: the same reset as the stage-level `reset`.

## Notes on the `exec` and `background` Type

When a `cc` command is configured, minimega will send the command to a `miniccc`
agent every time it connects or reconnects. This means a command may actually be
executed more than once (for example, if a VM running the `miniccc` agent is
rebooted). This is useful when `cc` is used for actions like setting IPs or
default routes, but may not be useful for most of the actions executed as part
of this component. The `once` setting can be used to limit the execution of an
exec or background command to only one time (and this is the default for this
setting).

A VM-level `exec` can `wait` for the command to finish; the stage then fails if
the command exits non-zero (on Windows, if it writes anything to stderr). A
`validator` is a bash script run **on the phenix host** (not in the VM) with the
command's stdout on its stdin and the VM's hostname as its first argument; a
non-zero exit fails the stage, and whatever the script writes to stderr is shown
to the user. Setting a `validator` forces `wait`.

> [!IMPORTANT]
> Validators run as shell scripts on the phenix host, not in the VM. To lock
> this down, set `PHENIX_SCORCH_HOST_VALIDATORS=0` in the phenix environment;
> each validator is then skipped with a warning and the result is not validated.

## Notes on Stage-Level `args` and `filter`

A stage-level `exec` hands `args` and `filter` to minimega as written, so
minimega's command lexer reads them: `#` starts a comment and drops the rest,
quotes group words, and a backslash is an escape (only `\\`, `\'`, `\"`, `\n`,
`\r`, `\t` and `\#` are valid; any other fails the command). Write Windows
paths with forward slashes. VM-level `exec` and `background` write `args` to a
script on the VM instead, so none of this applies to them.

## Notes on the `send` Type

When sending a file with `send`, the source and destination can be specified by
separating them with a colon (`:`). If a colon is not present, then it is
assumed that the file should be placed in the same location in the VM as it is
on the phenix host.

For example, if `/tmp/file.txt:/file.txt` is provided, then the file located at
`/tmp/file.txt` on the phenix host will be placed at `/file.txt` in the VM. If
the VM is a Windows VM, this will translate to `C:\file.txt`.

If only `/tmp/file.txt` is provided, then it will be placed at `/tmp/file.txt`
in the VM. If the VM is a Windows VM, this will translate to `C:\tmp\file.txt`.

If either path is a relative path, then it's assumed to be relative to the
`/phenix` directory on the phenix host and/or the VM.

## Notes on the `recv` Type

When receiving a file with `recv`, the source and destination can be specified
by separating them with a colon (`:`). If a colon is not present, then it is
assumed that the file should be placed in the appropriate location on the phenix
host for the current scorch run, loop, and count.

> In most cases, it's recommended to only provide the source path and let the
> file be placed in the appropriate location on the phenix host.

## Examples

Reset miniccc state at the start and end of a run, run a stage-level command
against every VM tagged `role:web`, and bring an interface down for the run.

```yaml
components:
  - name: reset_miniccc
    type: cc
    metadata:
      configure:
        - type: reset
      cleanup:
        - type: reset
  - name: restart-foobar
    type: cc
    metadata:
      start:
        - type: exec
          filter: tag=role:web
          args: service foobar restart
          once: true
  - name: disable-eth0
    type: cc
    metadata:
      vms:
        - hostname: foobar
          start:
            - type: exec
              args: ip link set eth0 down
              wait: true
          stop:
            - type: exec
              args: ip link set eth0 up
```

Run a check on a VM and fail the run unless its output is right, background a
logger, and copy a result file back to the SCORCH run folder.

```yaml
components:
  - name: check-ssh-listening
    type: cc
    metadata:
      vms:
        - hostname: scada
          start:
            - type: exec
              args: ss -tlnp
              validator: |
                grep -q ':22 ' <<< "$(cat)" || {
                  echo "$1: sshd is not listening on port 22" >&2
                  exit 1
                }
            - type: background
              args: logger -t scorch monitoring started
          stop:
            # retrieves "/root/result.txt" into the SCORCH output directory
            - type: recv
              args: /root/result.txt
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `start.0: Input tag 'background' found using 'type' does not match any of the expected tags: 'reset', 'exec'` | A VM-level command type (`background`, `send`, `recv`) was put in a top-level stage list, which only takes `reset` and `exec`. Move it under a `vms` entry. |
| `vms.0.start.0: Input tag 'foo' found using 'type' does not match any of the expected tags: 'exec', 'background', 'send', 'recv', 'reset'` | Unknown VM-level command `type`. Use one of the listed types. |
| `start.0.exec.args: Field required` (or `vms.0.start.0.exec.args`) | An `exec` with no `args`. `send` and `recv` need `args` the same way. |
| `start.0.exec.args: String should match pattern '^[^\x00\r\n]*$'` | A stage-level `exec`/`filter` with a newline or NUL. Write it on one line. |
| `vms.0.start.0.send.args: Value error, expected 'src' or 'src:dst' (at most one ':')` | A `send`/`recv` `args` with more than one `:`. Use `src` or `src:dst`. |
| `vms.0.hostname: Value error, not a valid hostname: 2 to 63 letters, digits and interior hyphens` | `hostname` is not a topology node name. |
| `<hostname> is not in the topology` (logged) | A `vms` entry names a VM that is not in the experiment; its commands are skipped. Fix the hostname. |
| `command '<args>' failed` / `command '<args>' failed on Windows` | A waited `exec` exited non-zero (on Windows, wrote to stderr). The logged STDERR says why. |
| `results validation failed: <stderr>` | The `validator` script exited non-zero; its stderr is shown. |
| `skipping host-side validator for command '<args>' on VM <hostname>: host-side commands are disabled by PHENIX_SCORCH_HOST_VALIDATORS=0` (logged) | `PHENIX_SCORCH_HOST_VALIDATORS=0` is set, so validators are not run. Unset it to validate. |
| `path '<path>' escapes base directory '<base>'` | A `recv` absolute destination points outside the SCORCH run folder. Use a relative path or one inside the folder. |
| `error sending '<src>' to VM <hostname>: <minimega error>` / `error receiving ...` | minimega refused the transfer; the `<minimega error>` says why. Check the path and that the VM is running. |

## Limitations

- A `reset` clears all miniccc commands and responses for the namespace, which
  disrupts other components; use it only at the edges of a run or loop.
- A `background` command keeps running after the component finishes.
- `validator` scripts run on the phenix host, not in the VM.
