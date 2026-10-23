# minimega (mm) Component

Runs minimega actions at chosen points of a SCORCH run: packet captures on a
bridge or on VM interfaces, starting and stopping VMs, and connecting or
disconnecting VM interfaces from VLANs. Use it to script changes to a running
experiment, such as cutting a link mid-run or capturing only during an attack.

```
type:   mm
exe:    phenix-scorch-component-mm
stages: configure, start, stop, cleanup
```

In each stage the component runs the top-level bridge commands for that stage,
in order, then each `vms` entry's commands for that stage, in order.

| Command | Where | What it does |
|---|---|---|
| `start_capture` | bridge | Starts a capture of everything on `capture.bridge`, written to `capture.filename` (default `<bridge>-<UTC time>.pcap`) |
| `stop_capture` | bridge | Stops the capture on `capture.bridge` and copies the capture files back to the head node; with `capture.convert`, converts them to JSON |
| `start` | VM | Starts the VM |
| `stop` | VM | Stops (pauses) the VM |
| `connect` | VM | Connects interface `connect.interface` to VLAN `connect.vlan` (on `connect.bridge`, or the bridge it was on). Moves an already connected interface |
| `disconnect` | VM | Disconnects interface `disconnect.interface` |
| `start_capture` | VM | Starts a capture on interface `capture.interface`, written to `capture.filename` (default `<hostname>-<interface>-<UTC time>.pcap`) |
| `stop_capture` | VM | Stops the capture on `capture.interface`, or every capture on the VM if that is not set, and copies the files back; with `capture.convert`, converts them |

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
<bridge>-<UTC time>.pcap               a bridge capture (or your filename)
<hostname>-<interface>-<UTC time>.pcap a VM interface capture (or your filename)
<name>.pcap.jsonl                      with convert: Elasticsearch bulk JSON (tshark -T ek)
<stage>-<UTC time>.json                the SCORCH status file (logs, and the error on failure)
```

`.pcap` is added to a filename that does not end in it. The captures exist
from `start_capture` but are only complete, and only copied to the head node,
after the matching `stop_capture`.

## Before you start

- `convert` needs `tshark` on the host running phenix (the headnode).

## Metadata

Top level:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `configure`, `start`, `stop`, `cleanup` | list of bridge commands | none | Bridge commands for that stage |
| `vms` | list | none | VMs with their own commands |
| `transfer_poll_interval` | seconds > 0 | `2` | With `convert`, how often to check that the captures reached the head node |
| `convert_timeout` | seconds > 0 | `600` | With `convert`, how long to wait for the captures to reach the head node, and the limit for each `tshark` conversion. On timeout the component logs an error and carries on |

A bridge command:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | `start_capture` or `stop_capture` | yes | |
| `capture.bridge` | bridge name (up to 15 characters) | yes | Bridge to capture on (the experiment's bridge is usually `phenix`) |
| `capture.filename` | file name | no | For `start_capture`; letters, digits and `. _ : + -` only, no directory |
| `capture.filter` | BPF filter | no | For `start_capture`, as for tcpdump (`port 80`); no quotes, backslashes, `#` or line breaks |
| `capture.snaplen` | integer >= 0 | no | For `start_capture`: bytes kept per packet (`0` means minimega's 1600-byte default) |
| `capture.convert` | bool | no (`false`) | For `stop_capture`: convert the captures to JSON |

A `vms` entry:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `hostname` | word (no whitespace or quotes) | yes | VM in the experiment, or a minimega target such as `vm[1-3]` or `a,b` |
| `configure`, `start`, `stop`, `cleanup` | list of VM commands | no | Commands for that stage |

A VM command:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | `start`, `stop`, `connect`, `disconnect`, `start_capture` or `stop_capture` | yes | |
| `connect.interface`, `connect.vlan` | integer or word | for `connect` | Interface index (from `0`, in the topology's order) and the experiment's VLAN name or ID |
| `connect.bridge` | bridge name (up to 15 characters) | no | Bridge for the VLAN; defaults to the one the interface was on (minimega's default bridge if it was on none) |
| `disconnect.interface` | integer or word | for `disconnect` | Interface index |
| `capture.interface` | integer or word | for `start_capture` | Interface index to capture on |
| `capture.filename`, `capture.filter`, `capture.snaplen` | | no | As for a bridge capture |
| `capture.interface` | integer or word | no | For `stop_capture`: stop only this interface's capture (default: all of the VM's captures) |
| `capture.convert` | bool | no (`false`) | For `stop_capture` |

## Examples

Capture the experiment bridge (minus SSH) for the whole run, and convert it for
Elasticsearch at the end.

```yaml
components:
  - name: bridge-capture
    type: mm
    metadata:
      start:
        - type: start_capture
          capture:
            bridge: phenix
            filter: not port 22
      stop:
        - type: stop_capture
          capture:
            bridge: phenix
            convert: true
```

Cut an RTU off the network when the run starts and reconnect it when it stops,
capturing the SCADA server's first interface meanwhile.

```yaml
components:
  - name: rtu-outage
    type: mm
    metadata:
      vms:
        - hostname: rtu-1
          start:
            - type: disconnect
              disconnect:
                interface: 0
          stop:
            - type: connect
              connect:
                interface: 0
                vlan: ot
        - hostname: scada
          start:
            - type: start_capture
              capture:
                interface: 0
                filename: scada-outage.pcap
                snaplen: 1500
          stop:
            - type: stop_capture
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `start.0: Input tag 'connect' found using 'type' does not match any of the expected tags: 'start_capture', 'stop_capture'` | A VM command (`start`, `connect`, ...) was put in a top-level stage list. Move it under a `vms` entry. |
| `stop.0.stop_capture.capture.bridge: Field required` | A bridge capture without `capture.bridge`. |
| `vms.0.start.0.connect.connect: Field required` (or `disconnect.disconnect`, `start_capture.capture.interface`) | The command is missing its details block, or the interface. |
| `start.0.start_capture.capture.filename: String should match pattern '^[A-Za-z0-9._:+-]+$'` | A filename has a directory part or other characters. A word, or a `filter` (spaces allowed), with quotes fails the same way. |
| `default capture file name 'vm[1-3]-0-<time>.pcap' has characters outside letters, digits and . _ : + -; set capture.filename` | The default name is built from the VM target; set `capture.filename` when `hostname` is a pattern such as `vm[1-3]`. |
| `stop.0.stop_capture.capture.convert: Input should be a valid boolean, unable to interpret input` | `convert` must be `true` or `false`. |
| `unable to start pcap capture for bridge <bridge>: <minimega error>` | minimega refused the capture; the `<minimega error>` says why. Check the bridge name first. |
| `unable to start pcap capture for interface <i> on <vm>: <minimega error>` | minimega refused it; check the VM name and the interface index. |
| `unable to connect interface <i> on <vm> to VLAN <vlan>: <minimega error>` | Check the VM name, the interface index and the VLAN. |
| `unable to start vm <vm>: <minimega error>` / `unable to stop vm ...` | Check the VM name or pattern. |
| `unable to stop pcap capture ...: <minimega error>` | Stopping the capture or copying the files back failed; the `<minimega error>` says which. Check there is a matching `start_capture`. |
| `PCAP --> JSON conversion of <file> failed` | `tshark` is missing on the phenix host, exited with an error, or ran past `convert_timeout`. No `.jsonl` is written for that capture, so the next `stop_capture` with `convert` tries it again. |
| `pcap transfer to head node not done after <n>s` | The captures did not reach the head node within `convert_timeout`; nothing was converted. Raise `convert_timeout`. |

## Limitations

- A `start_capture` with no later `stop_capture` for the same bridge or VM
  interface keeps running after the run; the component logs a warning when it
  sees this.
- A bridge capture sees everything on the bridge, management traffic included;
  use a `filter`.
- `filter` and `snaplen` apply only to the capture started by the same command.
- Bridge captures only run on the headnode's minimega instance (the one phenix
  connects to), not on other nodes in the cluster. VM captures are written on
  the node running the VM.
