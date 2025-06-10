# providerdata Component

Collects and verifies data from pybennu providers, such as the RTDS or OPALRT.

```
type:   providerdata
exe:    phenix-scorch-component-providerdata
stages: configure, start, stop, cleanup
```

## Notes

- It is recommended to reset miniccc state before running `configure` stage of this component with run in a Scorch `loop`. An example of this is shown in the example section, with a `reset_cc` component used before `configure` is called. This isn't strictly required, but it will greatly increase reliability of the component when used with Scorch's `loop`.
- This component checks a variety of things on the provider: the VM is running, NTP is synchronized, and that the `pybennu-power-solver` process is running.
- Elasticsearch, if configured, must be reachable from the phenix Docker container.
- All data validation is performed via Elasticsearch. The CSV files are not used for validation and are simply copied during the `stop` stage. If data validation is important, ensure Elasticsearch configured in the provider and this component.

## Metadata Options

```yaml
metadata:
  hostname: <string>  # (REQUIRED) Hostname of the provider VM
  export_logs: <bool>  # (Optional) If the pybennu provider log files should be exported during the stop stage. Defaults to false.
  export_config: <bool>  # (Optional) If the provider configuration files (config.ini and *_config.yaml) should be exported during the configure and stop stages. Defaults to true.
  elasticsearch:
    verify: <bool>  # (Optional) If Elasticsearch data should be verified. Defaults to false.
    server: <bool>  # (REQUIRED) URL of the Elasticsearch server to use. Required if elasticsearch.verify is true.
    index: <string>  # (REQUIRED) Base name of Elasticsearch index with data to check. Required if elasticsearch.verify is true.
  csv_files:
    path: <string>  # (Optional) Path where the CSV files are on the provider. Defaults to /root/provider_data/
    export: <bool>  # (Optional) If CSV files should be saved off.  Defaults to false.

```

## Example Configuration

Example of using the component with the OPALRT provider.

```yaml
components:
  - name: providerdata_example
    type: providerdata
    metadata:
      hostname: power-provider
      export_logs: true
      export_config: true
      elasticsearch:
        server: http://192.0.2.10:9200
        index: opalrt-clean
        verify: true
      csv_files:
        path: /root/opalrt_data/
        export: false
  - name: reset_cc
    type: cc
    metadata:
      configure:
        - type: reset
runs:
  - configure: []
    start: []
    stop: []
    cleanup: []
    loop:
      count: 3
      configure:
        - reset_cc
        - providerdata_example
      start:
        - providerdata_example
      stop:
        - providerdata_example
      cleanup:
        - providerdata_example
```
