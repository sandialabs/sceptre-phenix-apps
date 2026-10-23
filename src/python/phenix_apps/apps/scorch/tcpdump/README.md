# tcpdump Component

Runs `tcpdump` inside VMs through miniccc, then copies the captures back and
can convert them to JSON for Filebeat. The `pcap` component captures from
outside the VM with minimega instead.

```
type:   tcpdump
exe:    phenix-scorch-component-tcpdump
stages: start, stop
```

| Stage | What it does |
|---|---|
| `start` | For each VM: checks `tcpdump` is installed and the interface exists, stops a tcpdump left behind by an earlier failed `stop` (found through `/dump-<iface>.pid`), brings the interface up, and starts `tcpdump <options> -i <iface> -U -w /dump-<iface>.pcap <filter>` in the background from a launcher script it sends to the VM, recording its PID in `/dump-<iface>.pid` and its stderr in `/dump-<iface>.err`. |
| `stop` | For each VM: stops the tcpdump whose PID is in `/dump-<iface>.pid` (other tcpdumps are left alone), copies the capture to the run directory, deletes the capture, PID file and stderr file from the VM, and optionally converts it to JSON. |

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
<hostname>-<iface>.pcap         one per VM and interface
<hostname>-<iface>.pcap.jsonl   only with convert_to_json
```

The JSON file is named `.pcap.jsonl`, unlike the `pcap` component's `.jsonl`,
so a Filebeat path written for one does not match the other.

## Before you start

- Linux guests with `tcpdump` installed, the VM powered on with its miniccc
  client running and registered, and a writable `/` with room for the capture.
- `tshark` on the headnode (the host running phenix, not the VMs), for
  `convert_to_json`.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `vms` | list | yes | | VMs to capture in, at least one. Each VM and `iface` once |
| `vms[].hostname` | name | yes | | VM in the topology: 2 to 63 letters, digits and interior hyphens |
| `vms[].iface` | interface | yes | | Interface name as the guest OS sees it (`eth1`), not the topology's name for it. Up to 15 letters, digits, `_`, `.` or `-`. `any` captures on every interface |
| `vms[].options` | string | no | | Extra tcpdump options (`-c 1000 -s 96`), no single quotes. Do not pass `-i`, `-U` or `-w`; the component adds them |
| `vms[].filter` | string | no | | tcpdump filter expression (`port 80`), no single quotes |
| `convert_to_json` | bool | no | `false` | Convert each capture to Elasticsearch bulk JSON (`tshark -T ek`). The old name `convertToJSON` still works but is deprecated and logs a warning |
| `convertTimeout` | seconds | no | `600` | Longest a single capture's conversion may take. On expiry an error is logged and `stop` carries on; that `.pcap.jsonl` is incomplete. Raise it for large captures |

## Examples

Capture the first thousand HTTP packets seen inside one VM.

```yaml
components:
  - name: tcpdump-http
    type: tcpdump
    metadata:
      vms:
        - hostname: sniffer
          iface: eth1
          options: -c 1000
          filter: port 80
```

Capture two VMs and ship the results to Elasticsearch through Filebeat. phenix
reads `filebeat.inputs` from the component metadata (this component ignores
it).

```yaml
components:
  - name: tcpdump-filebeat
    type: tcpdump
    metadata:
      convert_to_json: true    # Filebeat needs the .pcap.jsonl files
      vms:
        - hostname: rtu-1
          iface: eth0
        - hostname: scada
          iface: eth1
          filter: not port 22
      filebeat.inputs:
        - type: log
          enabled: true
          paths:
            - "*.pcap.jsonl"
          processors:
            - decode_json_fields:
                fields:
                  - message
                target: scorch.tcpdump
            # tshark -T ek writes an index line before each packet; drop those
            - drop_event:
                when:
                  has_fields:
                    - scorch.tcpdump.index._type
            - drop_fields:
                fields: ["message"]
            - timestamp:
                field: scorch.tcpdump.timestamp
                layouts:
                  - UNIX_MS
```

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `interface <iface> does not exist in VM <vm>` (at `start`) | `iface` is not the guest's name for the interface (check `ip link` in the VM). |
| `tcpdump is not installed in VM <vm>` | `which tcpdump` found nothing in the guest. Install tcpdump in the image. |
| `['/dump-<iface>.pcap'] not found in VM <vm>` (at `stop`) | tcpdump never wrote the capture. Check that the VM was running at `start`, that `iface` is the guest's name for the interface, that `options` and `filter` are valid and have no `-i` or `-w`, and that `/` has room. |
| `timed out after <grace>s waiting for miniccc client on VM <vm> (uuid ...)` | miniccc is not running in the guest, or the VM is down. Start it, or wait longer (`PHENIX_CC_*` settings). |
| `vms.0.iface: Field required` | `iface` is missing (also what you see if you wrote `interface:`). |
| `could not stop tcpdump in VM <vm> using /dump-<iface>.pid` (logged at `stop`) | The PID file is missing or its process is gone, so tcpdump may have exited early or never started; read `/dump-<iface>.err` in the VM for why. `stop` carries on and collects what exists. |
| `PCAP --> JSON conversion of <file> failed` or `timed out` (logged at `stop`) | `tshark` is missing on the headnode, rejected the capture, or exceeded `convertTimeout`. `stop` carries on; that `.pcap.jsonl` is empty or incomplete. |
| `<name> is in a start list but not in the matching stop list` / `listed after the collector in stop` (warning at `start`) | List the component in `stop`, before `collector`, so its captures are collected. |

## Limitations

- A `-c N` in `options` ends the capture early; the shorter file is still
  collected.
- Order matters: list `tcpdump` in `start` before the traffic and in `stop`
  after it. `start` warns if it is missing from `stop` or listed after
  `collector`.
