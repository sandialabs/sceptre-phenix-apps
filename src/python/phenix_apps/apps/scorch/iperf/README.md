# iperf Component

Collects network performance measurements using [iperf3](https://github.com/esnet/iperf) or [rperf](https://github.com/opensource-3d-p/rperf).

```
type:   iperf
exe:    phenix-scorch-component-iperf
stages: configure, start, stop, cleanup
```

## Notes

- Only Linux and Windows hosts are supported (`hardware.os_type` is either `linux` or `windows`).
- The `hardware.os_type` field must be defined for all hosts that will be configured for iperf.
- There must be an iperf or rperf executable on the VM, either via an inject or baked into the image. The path to this executable must be specified in the component metadata.
- `rperf` ([opensource-3d-p/rperf](https://github.com/opensource-3d-p/rperf)) may be used instead of `iperf3`. Update the executable paths to point to the rperf binary, and set `use_rperf` to `true`. Note that the results of `rperf` will NOT be processed and will not be ingested into Elasticsearch by Filebeat. At this time, it is intended to only be used to generate traffic. In the future we'd like to implement more robust parsing and configuration of `rperf`.
- This component utilizes minimega "tags", and will apply a `iperf` tag to each VM during the `configure` stage. These tags will be removed during the `cleanup` stage. The purpose of this is to improve the efficiency of miniccc commands by leveraging miniccc "filters".

## Metadata Options

```yaml
metadata:
  create_histogram: <bool>  # (Optional) If a histogram summary text file should be generated from the results. This is run during the "stop" stage. Default: true

  collect_netstat_info: <bool>  # (Optional) Used for debugging purposes. Runs the 'netstat' and 'ss' commands on Linux, 'netstat' on Windows, and saves the results to files. This is run during the 'stop' stage. Default: false

  run_duration: <float>  # (REQUIRED) How long to run iperf for, in seconds

  iperf_version: <string>  # (Optional) The expected version of iperf. Used during verification in the "configure" stage.

  verify_execution: <bool>  # (Optional) If executable execution and version number should be checked during the configure stage of the first loop of the Scorch run. Default: false

  iperf_paths:  # REQUIRED
    windows: <string>  # Path to iperf/rperf executable on Windows nodes
    linux: <string>  # Path to iperf/rperf executable on Linux nodes

  server_startup_delay: <float>  # (Optional) Seconds to wait for iperf server processes to start, defaults to 5 seconds

  # rperf
  use_rperf: <bool>  # (Optional) Default: false

  server_startup_delay: <float>  # (Optional) Seconds to wait for iperf server processes to start. Default: 5.0

  # refer to iperf3 documentation for additional options
  # https://iperf.fr/iperf-doc.php
  add_server_args: <string>  # (Optional) String of arguments to add to the iperf3 command line invocation for all iperf servers
  add_client_args: <string>  # (Optional) String of arguments to add to the iperf3 command line invocation for all iperf clients
  bandwidth: <int>  # (Optional) integer number of bits/sec to attempt to maintain during measurements (default 1 Mbit/sec for UDP, unlimited for TCP). Default: null

  # Defines what hosts will be LISTENING for iperf connections by running
  # an iperf server, and which hosts will be CONNECTING to those servers
  # with an iperf client.
  servers:
    - hostname: <string>  # (REQUIRED)
      port_range_start: <int>  # (REQUIRED)
      clients:  # (REQUIRED)
        - hostname: <string>  # (REQUIRED)
          add_server_args: <string>  # (Optional) overrides the options for all clients
          add_client_args: <string>  # (Optional) overrides the options for all clients
          bandwidth: <int>  # (Optional) overrides the options for all clients. Default: null

  filebeat.inputs:
    - type: filestream
      id: iperf-input
      enabled: true
      paths:
        # Example: iperf_server-data_client-load5_server-load8.json
        - iperf_server-data_*.json
        - iperf_client-data_*.json
      # NOTE: ndjson doesn't work when the whole file is one JSON object
      parsers:
        - multiline:
            type: pattern
            pattern: '^\{$'
            negate: true
            match: after
            max_lines: 100000
      processors:
        - decode_json_fields:
            fields:
              - message
            target: iperf
            add_error_key: true
        - add_fields:
            target: network
            fields:
              application: iperf
              type: ipv4
        - extract_array:
            field: iperf.start.connected
            mappings:
              iperf.connected: 0
        # Client
        - if:
            has_fields: ["iperf.start.connecting_to"]
          then:
            - add_fields:
                target: event
                fields:
                  dataset: client
            - rename:
                fields:
                  - from: iperf.connected.local_host
                    to: client.ip
                  - from: iperf.connected.local_port
                    to: client.port
                  - from: iperf.connected.remote_host
                    to: server.ip
                  - from: iperf.connected.remote_port
                    to: server.port
                  - from: iperf.end.sum_sent.bytes
                    to: network.bytes
        # Server
        - if:
            has_fields: ["iperf.start.accepted_connection"]
          then:
            - add_fields:
                target: event
                fields:
                  dataset: server
            - rename:
                fields:
                  - from: iperf.connected.local_host
                    to: server.ip
                  - from: iperf.connected.local_port
                    to: server.port
                  - from: iperf.connected.remote_host
                    to: client.ip
                  - from: iperf.connected.remote_port
                    to: client.port
                  - from: iperf.end.sum_received.bytes
                    to: network.bytes
        - convert:
            fields:
              - {from: "iperf.intervals.sum.seconds", type: "float"}
              - {from: "iperf.intervals.sum.start", type: "float"}
              - {from: "iperf.intervals.sum.bits_per_second", type: "float"}
              - {from: "iperf.intervals.streams.seconds", type: "float"}
              - {from: "iperf.intervals.streams.start", type: "float"}
              - {from: "iperf.intervals.streams.bits_per_second", type: "float"}
            ignore_missing: true
        - rename:
            fields:
              - from: iperf.start.system_info
                to: iperf.system_info
              - from: iperf.start.test_start.protocol
                to: network.transport
        - copy_fields:
            fields:
              - from: iperf.end.sum_received.seconds
                to: event.duration
              - from: client.ip
                to: client.address
              - from: server.ip
                to: server.address
        - timestamp:
            # Tue, 13 Feb 2024 15:59:44 GMT
            field: iperf.start.timestamp.time
            target_field: "@timestamp"
            layouts:
              - 'Mon, 2 Jan 2006 15:04:05 MST'
            test:
              - 'Tue, 13 Feb 2024 15:59:44 GMT'
        - timestamp:
            field: iperf.start.timestamp.time
            target_field: event.start
            layouts:
              - 'Mon, 2 Jan 2006 15:04:05 MST'
            test:
              - 'Tue, 13 Feb 2024 15:59:44 GMT'
        - dissect:
            field: iperf.start.version
            target_prefix: ""
            tokenizer: "iperf %{iperf.version}"
        - drop_fields:
            fields:
              - iperf.start.timestamp
              - iperf.start.version
              - iperf.start.connected
              - iperf.connected
              - message
              - input.type  # this will always be 'filestream'
              - log.flags  # this will always be 'multiline'
```

The `filebeat.inputs` section above can be blindly copied into user's own config
and used as-is, or users can choose to change target field names if the ones
used above aren't suitable.


## Example Configuration

```yaml
components:
  - name: iperf-example
    type: iperf
    metadata:
      create_histogram: true
      collect_netstat_info: true
      run_duration: 300.0  # 300 seconds  = 5 minutes
      iperf_version: "3.15"
      verify_execution: false

      iperf_paths:
        windows: /iperf-3.15-windows/iperf3.exe
        linux: /usr/bin/iperf3

      server_startup_delay: 5.0
      add_server_args: ""
      add_client_args: ""
      bandwidth: 200000

      servers:
      - hostname: load6
          port_range_start: 6201
          clients:
            # load5 -> load6
            - hostname: load5
              add_server_args: ""
              add_client_args: ""
              bandwidth: null
            # load8 -> load6
            - hostname: load8
        - hostname: control-scada
          port_range_start: 6401
          clients:
            - hostname: load5   # port 6401
            - hostname: gen2    # port 6402
            - hostname: br75    # etc...
      filebeat.inputs:
        - type: filestream
          id: iperf-input
          enabled: true
          paths:
            - iperf_server-data_*.json
            - iperf_client-data_*.json
          parsers:
            - multiline:
                type: pattern
                pattern: '^\{$'
                negate: true
                match: after
                max_lines: 100000
          processors:
            - decode_json_fields:
                fields:
                  - message
                target: iperf
                add_error_key: true
            - add_fields:
                target: network
                fields:
                  application: iperf
                  type: ipv4
            - extract_array:
                field: iperf.start.connected
                mappings:
                  iperf.connected: 0
            - if:
                has_fields: ["iperf.start.connecting_to"]
              then:
                - add_fields:
                    target: event
                    fields:
                      dataset: client
                - rename:
                    fields:
                      - from: iperf.connected.local_host
                        to: client.ip
                      - from: iperf.connected.local_port
                        to: client.port
                      - from: iperf.connected.remote_host
                        to: server.ip
                      - from: iperf.connected.remote_port
                        to: server.port
                      - from: iperf.end.sum_sent.bytes
                        to: network.bytes
            - if:
                has_fields: ["iperf.start.accepted_connection"]
              then:
                - add_fields:
                    target: event
                    fields:
                      dataset: server
                - rename:
                    fields:
                      - from: iperf.connected.local_host
                        to: server.ip
                      - from: iperf.connected.local_port
                        to: server.port
                      - from: iperf.connected.remote_host
                        to: client.ip
                      - from: iperf.connected.remote_port
                        to: client.port
                      - from: iperf.end.sum_received.bytes
                        to: network.bytes
            - convert:
                fields:
                  - {from: "iperf.intervals.sum.seconds", type: "float"}
                  - {from: "iperf.intervals.sum.start", type: "float"}
                  - {from: "iperf.intervals.sum.bits_per_second", type: "float"}
                  - {from: "iperf.intervals.streams.seconds", type: "float"}
                  - {from: "iperf.intervals.streams.start", type: "float"}
                  - {from: "iperf.intervals.streams.bits_per_second", type: "float"}
                ignore_missing: true
            - rename:
                fields:
                  - from: iperf.start.system_info
                    to: iperf.system_info
                  - from: iperf.start.test_start.protocol
                    to: network.transport
            - copy_fields:
                fields:
                  - from: iperf.end.sum_received.seconds
                    to: event.duration
                  - from: client.ip
                    to: client.address
                  - from: server.ip
                    to: server.address
            - timestamp:
                field: iperf.start.timestamp.time
                target_field: "@timestamp"
                layouts:
                  - 'Mon, 2 Jan 2006 15:04:05 MST'
                test:
                  - 'Tue, 13 Feb 2024 15:59:44 GMT'
            - timestamp:
                field: iperf.start.timestamp.time
                target_field: event.start
                layouts:
                  - 'Mon, 2 Jan 2006 15:04:05 MST'
                test:
                  - 'Tue, 13 Feb 2024 15:59:44 GMT'
            - dissect:
                field: iperf.start.version
                target_prefix: ""
                tokenizer: "iperf %{iperf.version}"
            - drop_fields:
                fields:
                  - iperf.start.timestamp
                  - iperf.start.version
                  - iperf.start.connected
                  - iperf.connected
                  - message
                  - input.type
                  - log.flags
```
