# pcap Component

Collects PCAPs from VMs via minimega's `capture pcap` API.

```
type:   pcap
exe:    phenix-scorch-component-pcap
stages: start, stop
```

| Stage | What it does |
|---|---|
| `start` | Starts a capture on each listed VM interface with its `filter` and `snaplen`. With `mode: namespace`, starts one capture of all listed VMs. With minimega before 3.4.0, first clears every `pcap` capture in the minimega namespace. |
| `stop` | Stops the captures, checks the state that minimega reports and every file with `capinfos`, optionally merges and de-duplicates them, writes `pcap_metadata.json`, and optionally converts the files to JSON. |

Capture happens in minimega's virtual switch, so the guests need nothing
installed.

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
<hostname>-<index>.pcap    one per listed VM interface (moved to raw/ with create_merged_pcap)
merged.pcap                only with create_merged_pcap, or with mode: namespace
raw/                       only with create_merged_pcap: the per-interface captures
pcap_metadata.json         capinfos output for each capture, and for merged.pcap
*.jsonl                    only with convert_to_json
```

With `format: pcapng`, the names end in `.pcapng`.

- File names use the interface's index, never its name: `interface: eth0` on a
  VM where `eth0` is the second interface gives `<host>-1.pcap`.
- With minimega 3.4.0 or later, each entry of `pcap_metadata.json` also has
  `minimega_state`, `minimega_packets` and `minimega_kdrops`. These come from
  minimega. `minimega_kdrops` is the number of packets the kernel dropped.
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
- `format: pcapng` and `mode: namespace` need minimega 3.4.0 or later on every
  node. The component reads the minimega version when it starts. With an older
  minimega, it keeps the behavior of the previous release, and these two
  fields fail with an error.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `vms` | list | yes | | VMs to capture on, at least one. Each VM and interface once |
| `vms[].hostname` | hostname | yes | | VM in the topology: 2 to 63 letters, digits and interior hyphens |
| `vms[].interface` | index or name | no | `0` | Interface to capture on: an index into the VM's interfaces (`0` is the first, which may be `MGMT`) or a Linux interface name (at most 15 characters) |
| `vms[].filter` | string | no | `filter` | BPF filter for this VM only, overriding `filter` |
| `vms[].snaplen` | integer >= 0 | no | `snaplen` | Snaplen for this VM only, overriding `snaplen` |
| `filter` | string | no | | BPF filter ([syntax](https://biot.com/capstats/bpf.html)), as for tcpdump (`not port 22`), for every VM without its own. May not contain `'`, `"`, `\`, `#` or line breaks (minimega would misread them) |
| `snaplen` | integer >= 0 | no | | Bytes kept per packet ([snaplen](https://wiki.wireshark.org/SnapLen)), for every VM without its own. `0` or unset is minimega's 1600-byte default. With minimega 3.4.0 or later, other values must be 14 to 65535 |
| `format` | `pcap` or `pcapng` | no | `pcap` | File format. `pcapng` needs minimega 3.4.0 or later |
| `mode` | `per_vm` or `namespace` | no | `per_vm` | `per_vm` makes one capture for each VM interface. `namespace` makes one capture of all listed VMs. See [Namespace mode](#namespace-mode) |
| `vlans` | list of VLAN names | no | all VLANs except `MGMT` | With `mode: namespace` only: the VLANs to capture |
| `create_merged_pcap` | bool | no | `false` | Merge all captures into `merged.pcap` with `mergecap`, moving the originals into `raw/` |
| `dedupe` | bool | no | `true` | Remove duplicate packets from `merged.pcap` with `editcap -d`. Only used with `create_merged_pcap` |
| `convert_to_json` | bool | no | `false` | Convert each capture to Elasticsearch bulk JSON (`tshark -T ek`), written next to it as `<name>.jsonl`. The old name `convertToJSON` still works but is deprecated and logs a warning |
| `merge_timeout` | seconds > 0 | no | `60` | How long `mergecap` and `editcap` may run |
| `tshark_timeout` | seconds > 0 | no | `120` | How long each `tshark` run may take when splitting DoS fragments |

### Namespace mode

With `mode: namespace`, minimega makes one capture of the traffic where it
enters the virtual switch from the ports of the listed VMs. Each frame is in
the file one time, so no `mergecap`, `editcap` or DoS special processing is
needed. The head node writes `merged.pcap` (or `merged.pcapng`), also for VMs on
other cluster hosts, so no transfer is needed.

- The capture includes all interfaces of the listed VMs on the selected VLANs.
  A `vms[].interface`, `vms[].filter` or `vms[].snaplen` is an error. Use
  `vlans` to select interfaces, and `filter` and `snaplen` for the whole
  capture.
- Without `vlans`, the capture includes all VLANs of the experiment except
  `MGMT`. To capture `MGMT`, list it in `vlans`.
- `create_merged_pcap` and `dedupe` are errors, because the capture is already
  one file.

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

One pcapng capture of two VMs on all VLANs except `MGMT`, written on the head
node (minimega 3.4.0 or later).

```yaml
components:
  - name: pcap-namespace
    type: pcap
    metadata:
      mode: namespace
      format: pcapng
      filter: not port 22
      vms:
        - hostname: rtu-1
        - hostname: scada
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
| `minimega capture failed: <path>: failed: <error>` | minimega stopped the capture because of the `<error>`, for example a full disk or a removed VM. The file can be short. |
| `mode: namespace requires minimega 3.4.0 or later; the oldest node runs <version>` | Also given for `format: pcapng`. Upgrade minimega on every node, or remove the field. |
| `snaplen <n> is not from 14 to 65535, the range minimega accepts for one capture` | Only with minimega 3.4.0 or later. Use `0` or a value in the range. |
| `no minimega namespace capture writes '<path>'` | `stop` found no running namespace capture. `start` did not run, or another command cleared it. |
| `the experiment has no VLAN besides MGMT to capture; set vlans` | Namespace mode has no VLAN to capture. Set `vlans`. |
| `vms.<n>.interface: not used with mode: namespace ...` | Also given for `filter` and `snaplen` of a VM. Remove the field, or use `mode: per_vm`. |
| `failed validation of PCAP metadata for file <path>` | `capinfos` ran but the file is not a pcap. |
| `PCAP merge failed, output file '<path>' doesn't exist` | `mergecap` produced nothing. Check the status file's logs. |

## Limitations

- With minimega 3.4.0 or later, `start` gives each capture its own filter and
  snaplen, and changes no namespace setting. A capture with no `filter` uses
  the namespace filter, which is no filter unless something else set one.
  Before 3.4.0, `start` resets minimega's filter (to the match-all
  `len >= 0`, because minimega drops an empty filter under a namespace) and
  snaplen once its captures are running.
- Bridge captures are not supported here; the [`mm` component](../mm/README.md)
  has them.
- With minimega 3.4.0 or later, `start` and `stop` change only the captures of
  this component. Before 3.4.0, `start` clears every pcap capture in the
  minimega namespace, including captures from other components such as `mm`,
  and logs a warning for each one it finds. Do not run two capturing
  components at once with such a minimega. `stop` ends only the capture on
  each listed interface, and clears minimega's capture settings only when no
  other capture is left.
- Captures write for the whole time between `start` and `stop`. Use `filter`
  and `snaplen` for long runs; `create_merged_pcap` needs room for a second copy
  and `convert_to_json` output is many times larger than the capture.
- Index `0` may be the `MGMT` interface; check the VM's interface order.
- List `pcap` in `start` before the traffic you want and in `stop` after it
  ends, and before `collector` in `stop`. Both stages log a warning when the
  component is missing from a `start` or `stop` list, or a `collector` is listed
  ahead of it in `stop`.
