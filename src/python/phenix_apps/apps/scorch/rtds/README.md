# rtds Component

Collects and verifies data from the Real-Time Dynamic Simulator (RTDS), and orchestrates the starting/stopping of RSCAD cases. This is intended to be used in tandem with the RTDS SCEPTRE provider.

```
type:   rtds
exe:    phenix-scorch-component-rtds
stages: configure, start, stop, cleanup
```

## Notes

- The `configure` stage has the side effect of clearing all miniccc commands and responses. Ensure this component is run before any other components that rely on miniccc state before execution, or are run in the background.
- This component checks a variety of things on the provider: the VM is running, NTP is syncronized, and that the `pybennu-power-solver` process is running.
- Elasticsearch, if configured, must be reachable from the phenix container running on the host.
- All data validation is done via Elasticsearch. The CSV files are simply copied off, and aren't used for validation. If validation is important, ensure Elasticsearch is setup and configured in the provider and in this component.

## Metadata Options

```yaml
metadata:
  hostname: <string>  # (REQUIRED) Hostname of the provider VM
  export_logs: <bool>  # (Optional) If the RTDS provider log files should be exported during the stop stage. Defaults to false.
  export_config: <bool>  # (Optional) If the RTDS provider configuration file (config.ini) should be exported during the configure stage. Defaults to false.
  rscad_automation:
    enabled: <bool>  # (Optional) Enable automation of RSCAD case (starting/stopping). Default: false
    url: <string>  # (REQUIRED) URL of RSCAD automation server. Only required if rscad_automation.enabled is true.
  elasticsearch:
    verify: <bool>  # (Optional) If Elasticsearch data should be verified. Defaults to false.
    server: <bool>  # (REQUIRED) URL of the Elasticsearch server to use. Required if elasticsearch.verify is true.
    index: <string>  # (REQUIRED) Base name of Elasticsearch index with data to check. Required if elasticsearch.verify is true.
    acceptable_time_drift: <float>  # (Optional) What level of time drift between RTDS and SCEPTRE is acceptable, in milliseconds. Time drift will only be checked if a value is specified here, and when elasticsearch.verify is true.
  csv_files:
    path: <string>  # (Optional) Path where the CSV files are on the provider. Defaults to /root/rtds_data/
    export: <bool>  # (Optional) If CSV files should be saved off.  Defaults to false.

```

## Example Configuration

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
      elasticsearch:
        server: http://172.24.24.121:9200
        index: rtds-clean
        verify: true
        acceptable_time_drift: 400.0
      csv_files:
        path: /root/rtds_data/
        export: true
```
