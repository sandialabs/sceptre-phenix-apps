# rtds Component

Collects and verifies data from the Real-Time Dynamic Simulator (RTDS), and
orchestrates the starting/stopping of RSCAD cases. This is intended to be used
in tandem with the RTDS SCEPTRE provider in pybennu.

```
type:   rtds
exe:    phenix-scorch-component-rtds
stages: configure, start, stop, cleanup
```

| Stage | What it does |
|---|---|
| `configure` | Checks the provider VM is running, optionally exports the provider config, checks `ntpq -p` on the provider, starts the RSCAD case if automation is enabled, and starts `pybennu-power-solver` if it is not running. |
| `start` | Fails unless the provider is running. Optionally checks that the CSV directory exists, and verifies data in Elasticsearch: new documents are arriving, the frequency is 60 ± 0.5 Hz, and the RTDS-to-SCEPTRE time drift is within limits. |
| `stop` | Stops the provider, and the RSCAD case if `rscad_automation.enabled`, then optionally exports the CSV directory, provider logs and provider config. |
| `cleanup` | Stops the provider, deletes the CSV directory and provider logs on the VM, and stops the RSCAD case (if enabled) without failing if it is already stopped. |

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
config.ini                 export_config: from /etc/sceptre/ (in configure, then again in stop)
rtds_config.yaml           export_config: from /etc/sceptre/ (in configure, then again in stop)
bennu-pybennu.out          export_logs: from /var/log/ (stop)
bennu-pybennu.err          export_logs: from /var/log/ (stop)
rtds_data/                 csv_files.export: the provider's CSV directory (stop)
configure-<UTC time>.json  one status file per stage that ran
start-<UTC time>.json
stop-<UTC time>.json
cleanup-<UTC time>.json
```

The CSV directory is copied to `<run folder>/<last part of csv_files.path>`. The
`stop` copy of the config files overwrites the one from `configure`.

The [collector](../collector/README.md) copies the `*.csv` files and config
files from this folder. It needs `export_config` (the default) and, for CSV
data, `csv_files.export`.

## Before you start

- The provider VM has pybennu installed (`/usr/local/bin/pybennu-power-solver`)
  and `ntpq` on its path.
- The RSCAD automation server (the GUI automation script on the RSCAD FX
  computer) is reachable from the phenix container, if `rscad_automation` is
  enabled.
- Elasticsearch is reachable from the phenix container, if
  `elasticsearch.verify` is true.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `hostname` | phenix node name | yes | | Provider VM |
| `export_logs` | bool | no | `false` | Export the pybennu logs in `stop` |
| `export_config` | bool | no | `true` | Export `/etc/sceptre/config.ini` and `rtds_config.yaml` in `configure` and `stop` |
| `provider_start_wait` | seconds >= 0 | no | `8` | How long `configure` waits after starting the provider, for it to reconnect to the PMUs |
| `rscad_automation.enabled` | bool | no | `false` | Start the RSCAD case in `configure` and stop it in `stop` and `cleanup` |
| `rscad_automation.url` | http(s) URL | when enabled | | RSCAD automation server |
| `rscad_automation.timeout` | seconds > 0 | no | `30` | How long to wait for the RSCAD automation server to answer |
| `rscad_automation.case_name` | file name | no | | Case file name without extension, for example `IEEE9BUSMJBLoads2`. If set, starting any other case stops it and fails. No path separators, no `.rtfx` or `.rtf`, none of `< > : " \| ? *` |
| `elasticsearch.verify` | bool | no | `false` | Verify the provider's data in `start` |
| `elasticsearch.server` | http(s) URL | when verifying | | Elasticsearch server |
| `elasticsearch.index` | string | when verifying | | Base index name; today's UTC date is appended (`rtds-clean-2026.10.13`) |
| `elasticsearch.acceptable_time_drift` | float > 0 | no | | Largest acceptable RTDS-to-SCEPTRE drift, in milliseconds. Not checked when unset |
| `elasticsearch.doc_count_wait` | seconds > 1 | no | `3` | Seconds between the two document counts; `(doc_count_wait - 1) * 1440` new documents must arrive |
| `csv_files.path` | directory | no | `/root/rtds_data` | Where the provider writes CSV files. `cleanup` runs `rm -rf` on it in a shell, so it must be an absolute directory below `/` (a file path with forward slashes and no shell characters), with no `.` or `..` segments |
| `csv_files.export` | bool | no | `false` | Copy the CSV directory into the run folder in `stop` |

Leave out `csv_files`, or leave it empty (`csv_files: {}`), to skip the CSV
check, export and deletion. Setting `csv_files` at all turns on the `start`
check and the `cleanup` deletion, even with `export: false`.

## Examples

Health checks only, nothing exported:

```yaml
components:
  - name: rtds-check
    type: rtds
    metadata:
      hostname: power-provider
      export_config: false
```

Full automation in a loop: RSCAD case control, Elasticsearch verification, and
every export.

```yaml
components:
  - name: rtds-example
    type: rtds
    metadata:
      hostname: power-provider
      export_logs: true
      export_config: true
      rscad_automation:
        enabled: true
        url: http://172.24.24.120:8000
        case_name: IEEE9BUSMJBLoads2
      elasticsearch:
        verify: true
        server: http://172.24.24.121:9200
        index: rtds-clean
        acceptable_time_drift: 400.0
      csv_files:
        path: /root/rtds_data/
        export: true
runs:
  - configure: []
    start: []
    stop: []
    cleanup: []
    loop:
      count: 3
      configure:
        - rtds-example
      start:
        - rtds-example
      stop:
        - rtds-example
      cleanup:
        - rtds-example
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `ntp on provider in INIT state, not synced. ntpq output: ...` | `ntpq -p` on the provider shows `.INIT.`, so NTP has not synced. Fix the provider's time source and wait. The check also needs `ntpq` on the VM. |
| `Starting RSCAD case failed: HTTP <code> from <url>` | The automation server answered with an error. Check `rscad_automation.url` and the server. |
| `Starting RSCAD case failed: <status>` | The server answered but reported failure. The status says why; check RSCAD on that computer. |
| `Expected RSCAD case 'X', but 'Y' was started` | The case that started is not `rscad_automation.case_name`. The component stopped it. Load the right case in RSCAD or fix the name. |
| `provider is not running!` | `start` found no `pybennu-power-solver`. Check `/var/log/bennu-pybennu.err` on the provider and that `configure` ran. |
| `expected 2880.0 documents created, but only N docs were created for index <idx>` | Fewer than `(doc_count_wait - 1) * 1440` new documents arrived. Either the PMUs are not producing, or this is not the reference 8-PMU setup (see Limitations). |
| `frequency out of bounds, expected 60 +-0.5, got X` | The latest frequency is outside 59.5 to 60.5 Hz. Check the RTDS case and the provider. |
| `no data in response from elasticsearch! the provider might be having issues.` | No document in the last 5 seconds. Check the provider is writing to this index. |
| `time drift of X ms > configured acceptable drift of Y ms (index=...)` | The average RTDS-to-SCEPTRE drift over the last 2 minutes is too large. Fix time sync, or raise `acceptable_time_drift`. |
| `no documents with rtds_time and sceptre_time in <idx> since now-2m, cannot check time drift` | No recent documents have both times. Check the provider and index, or unset `acceptable_time_drift`. |
| `url is required when enabled is true` | Set `rscad_automation.url`, or turn automation off. |
| `server required when verify is true` (or `index required ...`, or `server and index required ...`) | Set `elasticsearch.server` and `elasticsearch.index`, or set `verify: false`. |
| `rscad_automation.url: URL scheme should be 'http' or 'https'` | Use a URL like `http://host:8000`. `elasticsearch.server` fails the same way, even when `verify` is false. |
| `rscad_automation.case_name: Value error, must not include the file extension` | Use the case name only, without `.rtfx`. |
| `error receiving file ... not found in VM ...` | A file to export is missing on the provider: the config files, the logs, or the CSV directory. Check the paths, or turn the export off. |

## Limitations

- `configure` must have succeeded before `start`.
- List `rtds` in `stop` before the collector, so the exports exist when it
  copies them.
- CSV contents are never checked: `start` only runs `ls -lh` on the directory.
- The Elasticsearch checks assume the reference setup: 8 PMUs × 6 points × 30
  updates a second (at least 2,880 new documents in 3 seconds) and a 60 Hz
  system. Other setups fail `start` with verification on.
- The index date is taken in UTC when `start` runs, so a run that crosses
  midnight UTC checks the wrong day's index.
- TLS certificates of the RSCAD automation server are not verified.
