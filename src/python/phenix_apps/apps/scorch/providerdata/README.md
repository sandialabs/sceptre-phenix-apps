# providerdata Component

Collects and verifies data from pybennu providers, such as the RTDS or OPALRT.

```
type:   providerdata
exe:    phenix-scorch-component-providerdata
stages: configure, start, stop, cleanup
```

| Stage | What it does |
|---|---|
| `configure` | Checks the provider VM is running, optionally exports the provider config, checks NTP, and starts `pybennu-power-solver` if it is not running (then waits `start_wait` seconds for it to connect). |
| `start` | Fails unless `pybennu-power-solver` is running. Optionally checks the CSV directory exists and is growing and that today's Elasticsearch index has at least `elasticsearch.min_documents` documents, and optionally that new ones keep arriving and the grid frequency is right. |
| `cleanup` | Nothing. |
| `stop` | Optionally copies the CSV directory and provider logs, and exports the provider config again. |

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
config.ini                with export_config: the provider's /etc/sceptre/config.ini
<provider config>.yaml    with export_config: the YAML file config.ini names
bennu-pybennu.out, .err   with export_logs
<csv directory>/          with csv_files.export: the provider's CSV directory
<stage>-<UTC time>.json   the SCORCH status files (logs, and the error on failure)
```

The config is exported in both `configure` and `stop`, so it is in the folder
the `collector` component reads.

## Before you start

- The provider VM runs pybennu, with `/usr/local/bin/pybennu-power-solver`,
  `ntpq`, miniccc, and `/etc/sceptre/config.ini` naming its YAML config under
  `[power-solver-service] config-file`.
- Elasticsearch is reachable from where phenix runs, if `elasticsearch.verify`
  is true.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `hostname` | hostname | yes | | Provider VM |
| `export_logs` | bool | no | `false` | Copy the pybennu logs in `stop` |
| `export_config` | bool | no | `true` | Copy `config.ini` and the YAML config it names, in `configure` and `stop` |
| `start_wait` | seconds, 0 or more | no | `8` | Wait after starting `pybennu-power-solver`, for it to reconnect to its PMUs |
| `elasticsearch.verify` | bool | no | `false` | Check the provider's data reaches Elasticsearch in `start` |
| `elasticsearch.server` | http(s) URL | when verifying | | Elasticsearch server |
| `elasticsearch.min_documents` | whole number > 0 | no | `100` | Fewest documents today's index must hold |
| `elasticsearch.index` | word | when verifying | | Base index name; today's UTC date is appended (`opalrt-clean-2026.10.13`) |
| `elasticsearch.min_new_documents` | whole number > 0 | no | | Fewest new documents that must arrive during `doc_count_wait`; leave out to skip |
| `elasticsearch.doc_count_wait` | seconds > 0 | no | `3` | Wait between the two document counts |
| `elasticsearch.expected_frequency` | Hz > 0 | no | | Expected `measurement.frequency` of the newest document (from the last 5 seconds), such as `60`; leave out to skip |
| `elasticsearch.frequency_tolerance` | Hz > 0 | no | `0.5` | Allowed difference from `expected_frequency` |
| `csv_files.path` | Absolute Linux path, no `..`, spaces or shell characters | no | `/root/provider_data` | Where the provider writes CSV files |
| `csv_files.export` | bool | no | `false` | Copy that directory in `stop` |
| `csv_files.growth_wait` | seconds > 0 | no | `3` | Wait between the two size readings in `start` |

Leave out `csv_files`, or leave it empty, to skip the CSV check. With it, `start`
fails if the directory does not exist on the provider, or if the total size of its
files does not grow during `growth_wait` seconds (the provider is not writing).

## Example

An OPAL-RT provider in a three-iteration loop.

```yaml
components:
  - name: provider
    type: providerdata
    metadata:
      hostname: power-provider
      export_logs: true
      elasticsearch:
        verify: true
        server: http://192.0.2.10:9200
        index: opalrt-clean
      csv_files:
        path: /root/opalrt_data/
        export: true
runs:
  - configure: []
    start: []
    stop: []
    cleanup: []
    loop:
      count: 3
      configure: [provider]
      start: [provider]
      stop: [provider]
      cleanup: []
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `VM isn't running (vm name: <vm>)` | Start the provider VM before the run. |
| `ntp on provider in INIT state, not synced. ntpq output: ...` | NTP has not synchronised yet. Wait, or check the time server. |
| `/etc/sceptre/config.ini on <vm> does not name the provider's config file ...` | config.ini has no `[power-solver-service] config-file`. Fix the provider image, or set `export_config: false`. |
| `provider is not running!` | `pybennu-power-solver` stopped or never started. Check `/var/log/bennu-pybennu.err` on the provider. |
| `failed to run 'ls -lh <path>' ...` | `csv_files.path` does not exist on the provider. |
| `only N documents in <index> (expected at least <min_documents>); the provider does not appear to be sending data` | Elasticsearch answered, but the provider's data is not arriving. Check the provider's Elasticsearch settings, or the index name. |
| `only N new documents in <index> after <wait> seconds (expected at least <min_new_documents>)` | Data stopped arriving, or arrives slower than expected. Check the provider, or lower `min_new_documents`. |
| `frequency out of bounds, expected <expected_frequency> +-<tolerance>, got <value>` | The simulation's frequency is off. Check the model, or `expected_frequency` (`50` on a 50 Hz grid). |
| `no documents in <index> in the last 5 seconds` | Data stopped arriving before the frequency check. |
| `elasticsearch.server: Input should be a valid URL, relative URL without a base` or `... URL scheme should be 'http' or 'https'` | Use a URL like `http://host:9200`. It fails even when `verify` is false. |
| `CSV files in <path> on <vm> did not grow in <wait> seconds ...` | The provider is not writing CSV files. Check it is running and logging, or leave out `csv_files`. |
| `error receiving file '<path>' from VM <vm>: ...` | A config, log or CSV path is missing on the provider. |

## Limitations

- The frequency check reads one document's `measurement.frequency`; other
  values are not checked.
- The index date is taken in UTC when `start` runs, so a run that crosses
  midnight UTC checks the wrong day's index.
- `cleanup` does nothing: CSV and log files are left on the provider.
- List `providerdata` in `stop` before the `collector`, which reads its files.
