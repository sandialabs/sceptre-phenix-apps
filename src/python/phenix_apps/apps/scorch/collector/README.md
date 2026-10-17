# collector Component

Collects and processes data from cyber-physical experiments and Scorch components.
It gathers a run's output into one `experiment_results` folder, with an
`experiment_record.json` saying what ran, when, and with what settings.

```
type:   collector
exe:    phenix-scorch-component-collector
stages: stop
```

It was written for the HARMONIE experiments, so it expects their shape: a
`disruption` component, and usually `rtds` or `providerdata`.

## What you get

In the collector's own run folder
(`<files>/scorch/run-<run>/<collector name>/loop-<loop>-count-<count>/`):

```
experiment_results/
├── experiment_record.json     what ran, when, and how (see below)
├── experiment_results.csv     only with generate_csv
├── disruption/                the disruption component's output, as is
├── iperf/                     only with collect_iperf
├── pcaps/                     if a pcap component is in the run
├── provider_data/             *.csv from providerdata or rtds
└── metadata/
    ├── topology.yaml          phenix config get topology/<name>
    ├── scenario.yaml          phenix config get scenario/<name>
    ├── experiment.yaml        phenix config get experiment/<name>
    ├── vm_stats.jsonl         if vmstats is in the run
    ├── host_stats.jsonl       if hoststats is in the run
    ├── qos_values_applied.json  if qos is in the run
    └── *.ini, *.yaml, *.json, *.txt, *.out, *.err  from the provider
miniccc/                       only with collect_miniccc (next to experiment_results)
└── <vm>_miniccc.log
```

`experiment_record.json` has these top-level keys:

| Key | Contents |
|---|---|
| `experiment` | Disruption name, permutation, SCORCH count, start and end (UTC ISO and Kibana formats), configured and actual duration |
| `sceptre` | Experiment, topology and scenario names, minimega and phenix versions |
| `scorch` | Run, loop and count numbers |
| `disruption` | The disruption's configuration and its results files (`dos` attacker results, `physical` scenario results) |
| `qos` | The QoS values the `qos` component applied, if it ran |
| `provider` | Simulator type, PMU names, GTNET-SKT tags and Modbus registers from the provider config |
| `all_hosts` | Hostname to first-interface address, for every VM with more than one interface |
| `pcap_metadata` | `capinfos` output for each capture, if `pcap` ran |

The record's `end` is the start plus `run_duration`, not the actual stop time
(`end_time_actual`).

## Before you start

- A `disruption` component in the same run, with `current_disruption`
  (`baseline`, `dos`, `physical` or `cyber_physical`), `run_duration` and
  `permutation` set.
- Needs the `phenix` CLI on the PATH.

## Metadata

| Field | Type | Default | Meaning |
|---|---|---|---|
| `collect_iperf` | bool | `false` | Copy the `iperf` component's results into `iperf/` (empty `.log` files removed) and use them in the CSV |
| `collect_miniccc` | bool | `false` | Copy each VM's miniccc log into `miniccc/` (`/miniccc.log` from Linux VMs except `Router` nodes, `/minimega/miniccc.log` from Windows VMs). Every such VM must be running and have the log |
| `generate_csv` | bool | `false` | Write `experiment_results.csv` from Elasticsearch (needs `rtds` with `elasticsearch.server` and `elasticsearch.index`) |
| `pcap_duration_margin` | seconds | `6.0` | How much shorter the merged capture may be than the disruption's `run_duration` before the stage fails |

## Examples

A baseline run and its record.

```yaml
components:
  - name: baseline
    type: disruption
    metadata:
      current_disruption: baseline
      permutation: 0
      run_duration: 300.0
  - name: collector
    type: collector
    metadata: {}
runs:
  - configure: []
    start: [baseline]
    stop: [collector]
    cleanup: []
```

A full HARMONIE-style run: captures, iperf, the RTDS provider with
Elasticsearch, and a CSV. The collector is last in `stop`.

```yaml
components:
  - name: dos
    type: disruption
    metadata:
      current_disruption: dos
      permutation: 1
      run_duration: 300.0
      dos:
        attack_duration: 120.0
        start_delay: 60.0
        attacker:
          hostname: attacker
          script_path: /root/dos.py
          results_path: /root/attacker_results.json
        targets:
          - hostname: load5
  - name: pcap
    type: pcap
    metadata:
      create_merged_pcap: true
      vms:
        - hostname: load5
        - hostname: scada
  - name: iperf
    type: iperf
    metadata:
      run_duration: 300.0
      iperf_paths:
        linux: /usr/bin/iperf3
        windows: C:/iperf3.exe
      servers:
        - hostname: scada
          port_range_start: 6201
          clients:
            - hostname: load5
  - name: rtds
    type: rtds
    metadata:
      hostname: power-provider
      elasticsearch:
        verify: true
        server: http://elastic:9200
        index: rtds-clean
  - name: collector
    type: collector
    metadata:
      collect_iperf: true
      collect_miniccc: true
      generate_csv: true
runs:
  - configure: [rtds, iperf]
    start: [rtds, pcap, iperf, dos]
    stop: [rtds, pcap, iperf, collector]
    cleanup: [rtds, iperf]
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `the collector needs a 'disruption' component in this run's stages` | Add a `disruption` component and list its name in one of the run's stages. |
| `disruption component '<name>' is missing permutation, ...` | Add the listed keys to that disruption's metadata. |
| `Output directory doesn't exist for scorch component '<type>'` | That component did not run in this run. Add it to the run's stages. |
| `actual duration of N was less than the configured duration` | The disruption stopped before its `run_duration`. Check its status file. |
| `Capture duration N seconds is more than 6.0 seconds less than ...` | The merged capture is much shorter than the disruption. Raise `pcap_duration_margin` or fix the capture. |
| `Non-existent or empty config.ini from provider` | Set `export_config: true` on `rtds`, or make `providerdata` export it. |
| `error receiving file '/miniccc.log' from VM <vm>` | A VM has no miniccc log or is not running. Turn off `collect_miniccc` or fix the VM. |
| `the experiment record has no PMUs` | `generate_csv` needs PMUs in the RTDS provider config. |
| `'generate_csv' is true but 'rtds' component not enabled` | Add `rtds` to the run, or turn `generate_csv` off. |

## Limitations

- List the collector last in `stop`, so the components it collects from have
  written their output first. With `collect_iperf`, an `iperf` listed after
  the collector in a `stop` list is rejected with an error.
- Components are found by type (`disruption`, `pcap`, `iperf`, `vmstats`,
  `hoststats`, `qos`, `providerdata` or `rtds`) and only count if their name is
  in one of the run's stage lists. If several of one type are listed, only the
  first one defined in the scenario is collected; anything not found is skipped.
- A component that only ran in `configure` is read from the run-level
  `loop-0-count-0` folder when it has none for the current loop and count.
- The CSV only works with the RTDS provider and its Elasticsearch data.
