# collector Component

Collects and processes data from cyber-physical experiments and Scorch components.

```
type:   collector
exe:    phenix-scorch-component-collector
stages: stop
```

## Notes
- Supported components: `rtds`, `vmstats`, `hoststats`, `iperf`, `disruption`, `qos`, `pcap`

### Known issues
- This component is currently highly dependant on the `rtds` and `disruption` components. It assumes that the `rtds` component is configured to use Elasticsearch, and will use the Elasticsearch configuration from the `rtds` component's metadata.
- This component currently has a lot of assumptions baked in for the HARMONIE environment and should be used with caution.
- It assumes stage names match stage types, e.g. it expects that the `pcap` stage has `name: pcap` and `type: pcap`.
- It will attempt to collect data from all components supported (`rtds`, `vmstats`, `hoststats`, `iperf`, `disruption`, `qos`, `pcap`), regardless of if they're actually defined or enabled in the experiment's [Scenario](https://phenix.sceptre.dev/latest/configuration/#scenario). Ensure all components are defined in your experiment's scenario.

### Features
The role of the collector should be to:
- Gather all relevant files together into a defined structure
- Collect any additional data from running environment
    - Copying files from VMs (miniccc logs)
    - Running VM metadata
    - phenix configs (scenario, topology, experiment)
    - phenix metadata, including version
    - minimega version
    - scorch metadata
- Validate all expected data sources exist
- Check data validity
- Check data integrity (files parsable, etc.)

## Metadata Options

```yaml
metadata:
  collect_iperf: <bool>  # (Optional) If iperf data should be collected and processed. Default: false
  collect_miniccc: <bool>  # (Optional) If miniccc log files from VMs should be collected, if available. Default: false
```

## Example Configuration

```yaml
components:
  - name: collector-example
    type: collector
    metadata:
      collect_iperf: false
      collect_miniccc: false
```
