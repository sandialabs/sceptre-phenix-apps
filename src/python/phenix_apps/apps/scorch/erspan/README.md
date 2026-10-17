# ERSPAN Component

Mirrors an experiment's traffic, live, to a capture machine outside phenix.
It adds an ERSPAN tunnel port to the experiment's Open vSwitch bridge and an
OVS mirror that copies the experiment's VLANs into it. Optionally it also logs
in to the receiving machine over SSH and sets up the other end of the tunnel,
so a sensor or IDS there sees the traffic on a plain interface.

```
type:   erspan
exe:    phenix-scorch-component-erspan
stages: configure, cleanup
```

| Stage | On the phenix host (through minimega's `shell`) | On the receiver (with `remote_config`, over SSH) |
|---|---|---|
| `configure` | Adds tunnel port `local_interface` to `local_bridge` and sets mirror `scorch-<local_interface>` on every VLAN except `excluded_vlans`. Mirrors already on the bridge are left alone (with a warning). | Creates ERSPAN interface `remote_interface` and brings it up; with `remote_bridge`, adds it there and floods to every other port. First failure stops the rest. |
| `cleanup` | Removes mirror `scorch-<local_interface>` from `local_bridge` and deletes `local_interface`. | Removes the flood flow and bridge port, then deletes `remote_interface`. Every command is tried, and every failure is reported. |

Put it in `configure` and `cleanup` of the run, not `start` or `stop`; mirroring
is on from `configure` until `cleanup`.

## What you get

On the receiver, an interface (`erspan1` by default) carrying a copy of the
experiment's traffic: capture or analyse it there (`tcpdump -i erspan1`,
Zeek, Suricata). With `remote_bridge`, every other port on that bridge gets the
copy too.

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
erspan_metadata_configure.json   what `configure` did (see below)
erspan_metadata_cleanup.json     what `cleanup` did
<stage>-<UTC time>.json          the SCORCH status file (logs, and the error on failure)
```

The two `erspan_metadata_<stage>.json` files are a JSON list with one entry per
step the stage took, in order: `{"event": ..., "message": ..., "data": {...}}`.
`event` says which part ran (`config_component`, `config_local`, `config_remote`,
or the `cleanup_` equivalents). For each command run on the phenix host or the
receiver, `data` holds `host`, `cmd`, `stdout` and `stderr`, so this is the
place to look when a mirror or tunnel does not come up. The password is never
written to either file.

## Before you start

- GRE (IP protocol 47) must pass from the phenix host to `remote_ip`, which is
  the receiver's tunnel endpoint. Firewalls often drop it.
- `local_ip` must be the source address the receiver sees the tunnel arrive from, or the receiver drops everything.
- With `remote_config`: SSH to `ssh_ip` must work from where phenix runs
  (keys from an agent or the default key files of the user running phenix;
  `/root/.ssh` in a container; or `password`), `user` must be able to run
  `sudo ip link`, `sudo ovs-vsctl` and `sudo ovs-ofctl` without a password
  prompt, and `remote_bridge` must already exist.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `local_bridge` | interface name | yes | | The experiment's OVS bridge on the phenix host (`phenix` unless the experiment sets another; `ovs-vsctl list-br` shows it) |
| `local_ip` | IP address | yes | | The phenix host's source address towards `remote_ip`, as the receiver sees it. Only used with `remote_config`, but always checked |
| `remote_ip` | IP address | yes | | The receiver's tunnel endpoint |
| `local_interface` | interface name | no | `erspan1` | Name of the tunnel port added to `local_bridge` |
| `session_key` | integer 0 to 4294967295 (a number, not a quoted string) | no | `100` | ERSPAN key; must match on both ends |
| `excluded_vlans` | list of VLAN names | no | none | VLANs not to mirror (for example `mgmt`; a single name without a list also works). Matched against the experiment's VLAN names, ignoring case |
| `remote_config` | block | no | | Set up the receiver too. Leave it out (or empty) to configure only the phenix side |
| `remote_config.ssh_ip` | IP address | yes, in the block | | Where to SSH to |
| `remote_config.port` | integer, 1-65535 | no | `22` | SSH port |
| `remote_config.user` | string, 1-32 characters | yes, in the block | | User to log in as; needs passwordless `sudo` for `ip`, `ovs-vsctl`, `ovs-ofctl` |
| `remote_config.password` | string | no | | Password for `user`. Without it, SSH keys are used |
| `remote_config.ssh_timeout` | seconds, above 0 | no | none | Timeout for connecting, authenticating and for each command. Without it SSH waits forever |
| `remote_config.remote_interface` | interface name | no | `erspan1` | ERSPAN interface to create on the receiver |
| `remote_config.remote_bridge` | interface name | no | | OVS bridge on the receiver to attach the interface to and flood |

An *interface name* is 1 to 15 letters, digits, `_`, `.` or `-` (the Linux limit
for interface names), not starting with `-`, which the commands would read as an
option. IP addresses cannot carry an IPv6 scope (`fe80::1%eth0`).

## Examples

Phenix side only, for a receiver you set up yourself (it needs an ERSPAN
interface from `192.168.1.3` to `192.168.1.2` with key 100). The management
VLAN is not mirrored.

```yaml
components:
  - name: erspan-local-only
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      excluded_vlans:
        - mgmt
```

Both ends, feeding an OVS bridge on the receiver so every VM on it (a sensor
and an IDS, say) gets the same copy.

```yaml
components:
  - name: erspan-full
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      local_interface: erspan1
      session_key: 100
      excluded_vlans:
        - mgmt
      remote_config:
        remote_bridge: vmbr0
        remote_interface: erspan1
        ssh_ip: 192.168.1.3
        user: ubuntu
        password: ubuntu
        ssh_timeout: 30
```

Both ends, with the traffic on a plain interface on the receiver (capture with
`tcpdump -i erspan1` there).

```yaml
components:
  - name: erspan-interface-only
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      remote_config:
        ssh_ip: 192.168.1.3
        user: ubuntu
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `no VLANs left to mirror: the experiment has no VLANs, or excluded_vlans names all of them` | Nothing would be mirrored (an empty selection would make OVS mirror everything). Exclude fewer VLANs. |
| local `ovs-vsctl: no bridge named <name>` | `local_bridge` is not the experiment's bridge. Check the bridge name (`ovs-vsctl list-br` on the phenix host). |
| local `... because a port named erspan1 already exists ...` | A previous run's `cleanup` did not run. Run it, or `ovs-vsctl del-port <bridge> erspan1` on the phenix host. |
| `Remote command failed (exit code 1): sudo: a terminal is required to read the password ...` | `user` needs passwordless `sudo` on the receiver for `ip`, `ovs-vsctl` and `ovs-ofctl`. |
| `Remote command failed (exit code 2): RTNETLINK answers: File exists` | In `configure`: `remote_interface` already exists on the receiver, from a run without `cleanup` or a `configure` that failed halfway. Run `cleanup`, or `sudo ip link del erspan1` there. |
| `Remote command failed ...` from `ovs-vsctl` or `ovs-ofctl` (in `configure`) | `remote_bridge` does not exist on the receiver, or OVS is not running there. The interface was already created; run `cleanup` before retrying. |
| `Remote command failed (exit code 1): Cannot find device "erspan1"` (in `cleanup`) | The receiver's interface is already gone: `cleanup` ran before, or `configure` never created it. Nothing is left to clean up. |
| `local_ip: value is not a valid IPv4 or IPv6 address` (also `remote_ip`, `remote_config.ssh_ip`) | These must be IP addresses, not hostnames. |
| warning `bridge <name> already has mirrors ...` | Something else already mirrors on `local_bridge`. It is left alone, but its traffic and this component's may overlap. |
| warning `excluded_vlans names VLANs this experiment does not have ...` | A name in `excluded_vlans` matches no VLAN, so it excludes nothing. Check the spelling. |
| `[Errno None] Unable to connect to port 22 on <address>` | Nothing answers SSH at `ssh_ip` from where phenix runs. |
| `Authentication failed.` or `No authentication methods available` | Wrong `password`, a rejected key, or no key at all for the user running phenix. |
| no traffic arrives on the receiver | GRE (protocol 47) is blocked, the keys differ, the VLANs are excluded, or the phenix host sends from an address other than `local_ip` (check with `tcpdump -n proto 47` on the receiver). |

## Limitations

- A failed local command is logged as an error and recorded in
  `erspan_metadata_<stage>.json`, but does not fail the stage. A failed remote
  command does.
- A `configure` that fails on the receiver leaves the phenix side set up: run
  `cleanup` before trying again.
- Without `ssh_timeout`, SSH has no timeouts. The receiver's host key is
  accepted without checking.
