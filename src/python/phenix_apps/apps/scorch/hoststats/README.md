# hoststats Component

Collects statistics on minimega host(s). Runs in the background during Scorch
execution. Records CPU and memory commit, load, network rates and which VMs
each host runs, every few seconds, to `host_stats.jsonl`. Use it to check an
experiment was not starved for resources, or to correlate host load with
results.

```
type:   hoststats
exe:    phenix-scorch-component-hoststats
stages: start (runs in the background until stop)
```

| Stage | What happens |
|---|---|
| `start` | Starts sampling every `pollPeriod` seconds and keeps running in the background while the rest of the run goes on. |
| `stop` | phenix stops the background `start` (SIGTERM); the component writes what it still holds and exits. |

**Without `background: true`, `start` never returns and the run hangs**, because
the component waits for phenix to stop it.

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
host_stats.jsonl          one JSON object per host per sample
start-<UTC time>.json     the SCORCH status file, written when stop ends the start stage
```

Each `host_stats.jsonl` line has:

| Field | Meaning |
|---|---|
| `compute_name` | Host name |
| minimega's `host` fields | CPUs, CPU and memory commit, memory total and used, network commit and RX/TX rates, uptime, VM count and limit, as minimega reports them |
| `Load_1`, `Load_5`, `Load_15` | System load averages |
| `vm_list` | Sorted names of the experiment's VMs on that host (minimega's `vm info` in the experiment's namespace, so other experiments' VMs are not listed) |
| `timestamp` | Sample time, milliseconds since the Unix epoch |

minimega computes its VM-based numbers across all namespaces, so they include
other experiments on the same hosts; `vm_list` only lists this experiment's.

## Before you start

- Set **`background: true`** and list the component in **`start` and `stop`**
  of the same run (see the example).
- To send the data to Elasticsearch, configure Filebeat in the SCORCH app and
  add `filebeat.inputs` to this component's metadata; phenix reads it, this
  component does not.

## Metadata

| Field | Type | Default | Meaning |
|---|---|---|---|
| `pollPeriod` | number > 0 | `5` | Seconds between samples |
| `flushPeriod` | number | `pollPeriod` | Seconds between writes to `host_stats.jsonl`, rounded down to a whole number of samples. Anything below `pollPeriod` (including `0`) writes after every sample |
| `filebeat.inputs` | list | | Filebeat inputs for phenix (see the example) |

## Example

```yaml
components:
  - name: hoststats
    type: hoststats
    background: true
    metadata:
      pollPeriod: 5
      flushPeriod: 30
      filebeat.inputs:
        - type: filestream
          id: hoststats-input
          enabled: true
          paths:
            - host_stats.jsonl
          parsers:
            - ndjson:
                target: hoststats
                add_error_key: true
          processors:
            - timestamp:
                field: hoststats.timestamp
                layouts:
                  - UNIX_MS
                test:
                  - 1709228988101
            # copied to @timestamp above, so no need to keep it
            - drop_fields:
                fields:
                  - hoststats.timestamp
                  - input.type   # always "filestream"
runs:
  - configure: []
    start: [hoststats]
    stop: [hoststats]
    cleanup: []
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Symptom or error | Cause and fix |
|---|---|
| the run never gets past `hoststats` in `start` | `background: true` is missing on the component. |
| `host_stats.jsonl` is missing or empty | Every sample failed (see the next row). The file is written from the first sample on, then every `flushPeriod`. |
| warning `host stats poll failed, will retry: <error>` | minimega did not answer that sample. Sampling continues; persistent failures mean minimega is down or unreachable. |
| `pollPeriod: Input should be greater than 0` | `pollPeriod` must be a positive number of seconds. |

## Limitations

- When the run stops, buffered samples are written before the component exits;
  phenix allows 10 seconds for that.
- Samples still buffered are lost if the process is killed without SIGTERM.
