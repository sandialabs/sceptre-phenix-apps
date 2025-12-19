# phenix (kafka) Component
Collects and filters desired Kafka data into CSV/JSON format, so that Kafka data can be easily used by programs such as Excel. The output directory for the data is listed in the phenix log when the scorch component starts.
This component is called in the configure and cleanup stages.

```
type: kafka
exe:  phenix-scorch-component-kafka
```
<br />

## Metadata Options

```yaml
metadata:
    kafka_endpoints: [(ip, port)] # (REQUIRED) IP_address:port_number sending Kafka data
    csv: <bool> # (Optional) boolean indicating if the output should be a csv, if false we return a JSON file. Defaults to true
    wait_duration_seconds: <int> # (Optional) number of seconds to wait for topics to populate at the beginning of the experiment before exiting (defaults to 305 seconds)
    topics: [([filter:(key, value)], name)] # (Optional) a list containing all topics to subscribe to and key value pairs to filter by (see yaml example for formatting)
```
<br />

## Example Configuration

```yaml
- metadata:
    kafka_endpoints:
      - ip: "1.0.0.0"
        port: "9092"
    csv: false
    wait_duration_seconds: 700
    topics:
      - filter:
          - key: name # The name of a data type with in a topic that is being filtered by
            value: foo # The value of a key to filter by
          - key: deviceOn
            value: False
        name: ${BRANCH_NAME}.foo.bar* # Wildcards are acceptable in topic names; however, if you have duplicate topics, that topic data will not be duplicated in the logs
      - filter:
          - key: name
            value: bar* # Wildcards work for values
        name: ${BRANCH_NAME}.foo.bar2
```

## Example Pipeline

```yaml
runs:
  - name: kafka_pipeline
    configure:
      - kafka
    cleanup:
      - kafka
```