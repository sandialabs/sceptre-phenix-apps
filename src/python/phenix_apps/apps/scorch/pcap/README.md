# pcap Component

Collects PCAPs from VMs via minimega's `capture pcap` API.

```
type:   pcap
exe:    phenix-scorch-component-pcap
stages: start, stop
```

| Stage | What it does |
|---|---|
| `start` | Clears every `pcap` capture in the minimega namespace, applies `filter` and `snaplen`, and starts a capture on each listed VM interface. |
| `stop` | Stops the captures, checks every file with `capinfos`, optionally merges and de-duplicates them, writes `pcap_metadata.json`, and optionally converts the files to JSON. |

Capture happens in minimega's virtual switch, so the guests need nothing
installed.

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
<hostname>-<index>.pcap    one per listed VM interface (moved to raw/ with create_merged_pcap)
merged.pcap                only with create_merged_pcap
raw/                       only with create_merged_pcap: the per-interface captures
pcap_metadata.json         capinfos output for each capture, and for merged.pcap
*.jsonl                    only with convert_to_json
```

- File names use the interface's index, never its name: `interface: eth0` on a
  VM where `eth0` is the second interface gives `<host>-1.pcap`.
- The `collector` component copies the folder and puts `pcap_metadata.json` in
  its experiment record as `pcap_metadata`.
- Each `.jsonl` is written next to its source. With `create_merged_pcap` the
  originals are in `raw/`, so a Filebeat path of `*.jsonl` only finds
  `merged.jsonl`.

## Before you start

- The VMs exist in the topology and are running when `start` runs.
- The head node (the host running phenix) has `tshark`, `capinfos`, `editcap`
  and `mergecap` (the Wireshark command line tools). On Debian or Ubuntu:
  `sudo apt install -y tshark wireshark-common`.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `vms` | list | yes | | VMs to capture on, at least one. Each VM and interface once |
| `vms[].hostname` | hostname | yes | | VM in the topology: 2 to 63 letters, digits and interior hyphens |
| `vms[].interface` | index or name | no | `0` | Interface to capture on: an index into the VM's interfaces (`0` is the first, which may be `MGMT`) or a Linux interface name (at most 15 characters) |
| `vms[].filter` | string | no | `filter` | BPF filter for this VM only, overriding `filter` |
| `vms[].snaplen` | integer >= 0 | no | `snaplen` | Snaplen for this VM only, overriding `snaplen` |
| `filter` | string | no | | BPF filter ([syntax](https://biot.com/capstats/bpf.html)), as for tcpdump (`not port 22`), for every VM without its own. May not contain `'`, `"`, `\`, `#` or line breaks (minimega would misread them) |
| `snaplen` | integer >= 0 | no | | Bytes kept per packet ([snaplen](https://wiki.wireshark.org/SnapLen)), for every VM without its own. `0` or unset is minimega's 1600-byte default |
| `create_merged_pcap` | bool | no | `false` | Merge all captures into `merged.pcap` with `mergecap`, moving the originals into `raw/` |
| `dedupe` | bool | no | `true` | Remove duplicate packets from `merged.pcap` with `editcap -d`. Only used with `create_merged_pcap` |
| `convert_to_json` | bool | no | `false` | Convert each capture to Elasticsearch bulk JSON (`tshark -T ek`), written next to it as `<name>.jsonl`. The old name `convertToJSON` still works but is deprecated and logs a warning |
| `merge_timeout` | seconds > 0 | no | `60` | How long `mergecap` and `editcap` may run |
| `tshark_timeout` | seconds > 0 | no | `120` | How long each `tshark` run may take when splitting DoS fragments |

### Merging and duplicates

`editcap -d` compares each packet's length and MD5 hash with the previous four
packets and drops it if one matches, so the earliest copy is kept. Capturing
on both ends of a link sees each packet twice, which is what this removes.

When a `disruption` component in this run (its name is in one of the run's
stage lists, including `loop`) is running a `dos` or `cyber_physical`
disruption, its DoS targets get special handling, since a flood of identical
fragments would otherwise be collapsed. A disruption defined in the scenario
but not listed in this run is ignored. The first matching disruption is used.
For its targets:

1. The non-target captures are merged and de-duplicated.
2. Each target's capture is split into the fragmented (attack) packets and
   everything else. The rest is merged in and de-duplicated again.
3. The fragmented packets are merged in last, without de-duplication.

The `<name>_no_dos_fragments.pcap` files stay in `raw/` (not in
`pcap_metadata.json`, not converted to JSON) and the `<name>_fragmented.pcap`
files are deleted.

## Examples

Capture two RTUs and the SCADA server, leaving the files as they are.

```yaml
components:
  - name: pcap-plain
    type: pcap
    metadata:
      vms:
        - hostname: rtu-1        # interface 0
        - hostname: rtu-2
          interface: eth0
        - hostname: scada
          interface: 1
```

A filtered, truncated capture merged into one de-duplicated file and converted
to JSON, with the Filebeat input that ships the JSON to Elasticsearch. phenix
reads `filebeat.inputs` from the component metadata (this component ignores
it).

```yaml
components:
  - name: pcap-filebeat
    type: pcap
    metadata:
      filter: not port 22
      snaplen: 1500
      create_merged_pcap: true
      dedupe: true
      convert_to_json: true    # Filebeat needs the .jsonl files
      vms:
        - hostname: rtu-1
        - hostname: scada
          interface: 1
      filebeat.inputs:
        - type: log
          enabled: true
          paths:
            - "*.jsonl"
          processors:
            - decode_json_fields:
                fields:
                  - message
                target: scorch.pcap
            # tshark -T ek writes an index line before each packet; drop those
            - drop_event:
                when:
                  has_fields:
                    - scorch.pcap.index._type
            - drop_fields:
                fields: ["message"]
            - timestamp:
                field: scorch.pcap.timestamp
                layouts:
                  - UNIX_MS
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `'tshark' is unavailable on this host, which is required for PCAP processing` | Also given for `capinfos`, `editcap` and `mergecap`. Install the Wireshark command-line tools. It fails every stage. |
| `vms: Field required` | The metadata has no `vms` list. Add one. |
| `failed to find node "X" (config=...)` | `X` is not a VM in the topology. Fix the hostname. |
| `interface eth9 does not exist on node X` | No interface of that name on the VM. Use an existing name or an index. |
| `PCAP file doesn't exist: <path>` | `stop` found no file for a listed VM. `start` did not run, another component cleared the capture, or the VM was not running. |
| `failed validation of PCAP metadata for file <path>` | `capinfos` ran but the file is not a pcap. |
| `PCAP merge failed, output file '<path>' doesn't exist` | `mergecap` produced nothing. Check the status file's logs. |

## Limitations

- `start` resets minimega's filter (to the match-all `len >= 0`, because
  minimega drops an empty filter under a namespace) and snaplen once its
  captures are running, so they do not apply to captures other components
  start later.
- Bridge captures are not supported here; the [`mm` component](../mm/README.md)
  has them.
- `start` clears every pcap capture in the minimega namespace, including
  captures from other components such as `mm`, and logs a warning for each one
  it finds. Do not run two capturing components at once. `stop` ends only the
  capture on each listed interface, and clears minimega's capture settings only
  when no other capture is left.
- Captures write for the whole time between `start` and `stop`. Use `filter`
  and `snaplen` for long runs; `create_merged_pcap` needs room for a second copy
  and `convert_to_json` output is many times larger than the capture.
- Index `0` may be the `MGMT` interface; check the VM's interface order.
- List `pcap` in `start` before the traffic you want and in `stop` after it
  ends, and before `collector` in `stop`. Both stages log a warning when the
  component is missing from a `start` or `stop` list, or a `collector` is listed
  ahead of it in `stop`.
