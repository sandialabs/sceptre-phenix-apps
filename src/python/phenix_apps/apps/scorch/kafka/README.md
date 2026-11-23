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
    kafka_endpoints: [(ip, port)] # (Optional) the brokers, each an IP address (IPv4 or IPv6, not a hostname) and an integer port (1-65535). Defaults to 127.0.0.1:9092
    csv: <bool> # (Optional) a true boolean (not a string) indicating if the output should be a csv, if false we write JSON lines (ndjson). Defaults to true
    wait_duration_seconds: <int> # (Optional) integer number of seconds to wait for topics matching a wildcard name to appear at the beginning of the experiment (defaults to 305 seconds)
    topics: [([filter:(key, value)], name)] # (Optional) the topics to subscribe to, each with key value pairs to filter its own messages by (see the examples)
```

- With no `topics`, every topic whose name starts with the experiment name is
  kept.
- A topic `name` matches exactly, or by its prefix when it ends in `*` (only
  right wildcards). Each topic's `filter` applies to that topic's messages
  only. A message is kept when any one of its topic's filters matches (no
  `filter` keeps every message on the topic), and is written once.
- A filter `value` matches case-insensitively, and `*` in it is a wildcard.
- Output is `<name>_output.csv` (or `<name>_output.ndjson`) in the run's
  output directory. The CSV header is every key seen so far: when a message
  brings a new key, the file is rewritten under the wider header and earlier
  rows get an empty value in the new column.
- A message that is not a JSON object is skipped. The listener's own errors
  (that, or a broker it cannot reach) are in `<name>_listener.log` beside the
  output.
<br />

## Examples

Two topics, each with its own filters, written as JSON lines. Wildcards are
acceptable at the end of topic names; if two names match the same topic, its
data is not duplicated.

```yaml
components:
  - name: kafka-filtered
    type: kafka
    metadata:
      kafka_endpoints:
        - ip: "1.0.0.0"
          port: 9092
      csv: false
      wait_duration_seconds: 700
      topics:
        - filter:
            - key: name # The name of a data type within a topic that is being filtered by
              value: foo # The value of a key to filter by
            - key: deviceOn
              value: False
          name: ${BRANCH_NAME}.foo.bar*
        - filter:
            - key: name
              value: bar* # Wildcards work for values
          name: ${BRANCH_NAME}.foo.bar2
```

Everything the experiment publishes, as a CSV, from the broker on the local
host.

```yaml
components:
  - name: kafka-all
    type: kafka
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
