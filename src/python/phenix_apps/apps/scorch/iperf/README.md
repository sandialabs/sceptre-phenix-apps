# iperf Component

Collects network performance measurements using [iperf3](https://github.com/esnet/iperf) or [rperf](https://github.com/opensource-3d-p/rperf).
Use it to see how a disruption (a DoS, a link degradation) affects the traffic
between the hosts of an experiment.

```
type:   iperf
exe:    phenix-scorch-component-iperf
stages: configure, start, stop, cleanup
```

Each entry in `servers` is a VM that listens; each of its `clients` connects to
it. A server runs one iperf3 process per client, each on its own port, counting
up from `port_range_start`.

| Stage | What it does |
|---|---|
| `configure` | Writes `iperf_mapping.json`, tags every iperf VM `iperf=1`, optionally checks the executable and version, and kills leftover iperf processes and deletes leftover result and PID files. |
| `start` | Starts the servers, waits `server_startup_delay`, then starts the clients for `run_duration` seconds. It returns right after launching the clients (they run in the background); it does not wait for them. |
| `stop` | Does not wait for iperf to finish. It sleeps `stop_grace`, checks whether iperf3 is still running on any VM (sleeping `stop_grace` more if so), kills iperf on all VMs, sleeps `stop_grace`, then collects the client and server JSON results (one transfer per VM), fails if any `*.json` in the run folder has iperf's `error` field set, and writes RTT histograms. With `use_rperf` it only kills the processes (no collection, no histograms). |
| `cleanup` | Deletes result files on the VMs (not with `use_rperf`) and removes the `iperf` tag. |

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
iperf_mapping.json                              servers, clients, ports, IPs and file paths
iperf_client-data_client-<c>_server-<s>.json    iperf3 client results (the useful ones)
iperf_server-data_client-<c>_server-<s>.json    iperf3 server results for that client
iperf_client-log_client-<c>_server-<s>.log      client console output, Linux clients only
iperf_server-log_client-<c>_server-<s>.log      server console output, Linux servers only
rtt_histogram_<client>-<server>.txt             one RTT (seconds) per interval, with create_histogram
netstat_outputs.txt, ss_outputs.txt             only with collect_netstat_info
<stage>-<UTC time>.json                         one status file per stage
```

With `use_rperf`, only `iperf_mapping.json`, the optional netstat files and
the status files are written. The `collector` component copies these files when
its `collect_iperf` is on.

## Before you start

- **miniccc must be running in every iperf VM**; the component runs everything
  through it.
- **Every iperf VM needs `hardware.os_type` set** to `linux` or `windows` in the
  topology, and the matching `iperf_paths` entry.
- **The iperf3 (or rperf) executable must already be on the VM**, from an inject
  or baked into the image.
- **iperf3 must be 3.10 or newer.** 3.9 (Ubuntu 22.04's package) has no server
  `--idle-timeout` and refuses `--pidfile` on a client, so its servers and
  clients exit at once and `stop` finds no results.

## Metadata

Unknown top-level keys, such as `filebeat.inputs` below, are kept so other
parts of phenix can read them.

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `run_duration` | finite float > 0 | yes | | How long the clients run, in seconds. iperf3 takes whole seconds, so it is rounded up (at most 86395: iperf3 allows 86400, and servers wait 5 s longer) |
| `iperf_paths.linux` | file path (forward slashes, no spaces or shell characters) | for Linux VMs | | Executable on Linux VMs |
| `iperf_paths.windows` | file path (forward slashes, no spaces or shell characters) | for Windows VMs | | Executable on Windows VMs |
| `servers` | list, at least one | yes | | See below |
| `iperf_version` | non-empty string | no | | Version the executable's `--version` output must report: `3.17` matches 3.17 and 3.17.1, not 3.1 or 3.170 (`rperf <version>` with `use_rperf`). Quote it (`"3.10"`): unquoted YAML reads `3.10` as the number `3.1`, which fails |
| `verify_execution` | bool | no | `true` | Check the executable runs (and its version) in `configure`; skipped when the SCORCH count is above 1 |
| `server_startup_delay` | float >= 0 | no | `5.0` | Seconds between starting servers and clients |
| `use_rperf` | bool | no | `false` | Use rperf: one server process per server VM; results are not collected, histograms are not written, and cleanup keeps the files |
| `create_histogram` | bool | no | `true` | Write an RTT histogram per client in `stop` (skipped with `use_rperf`) |
| `collect_netstat_info` | bool | no | `false` | Save `netstat`/`ss` output in `stop`, for debugging. A failure here is logged, not fatal |
| `stop_grace` | float >= 0 | no | `5.0` | Seconds `stop` waits for iperf to finish (and again if still running), and after killing it |
| `client_port_offset` | integer > 0 | no | `1000` | Each client binds its local port (`--cport`) to its server port plus this, so a server port can be at most `65535 - client_port_offset` |
| `add_server_args` | string of letters, digits, spaces and `_ . , : = @ % / + -`; not `--json-stream` | no | | Extra iperf3 server arguments, for every client. `""` adds none |
| `add_client_args` | same as `add_server_args` | no | | Extra iperf3 client arguments, for every client. `""` adds none |
| `bandwidth` | integer > 0 | no | | Target bits/second (`--bitrate`; `--bandwidth` for rperf) |

Each `servers` entry:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `hostname` | hostname (phenix node-name rules) | yes | Server VM in the topology |
| `interface` | integer or interface name (15 characters or fewer) | no, default `0` | Interface to use: its index or name in the topology |
| `port_range_start` | integer 1-65535 | yes | Port for the first client; each further client gets the next port. No port may be used twice across servers |
| `clients` | list, at least one | yes | VMs that connect to this server |
| `clients[].hostname` | hostname (phenix node-name rules) | yes | Client VM in the topology |
| `clients[].interface` | integer or interface name (15 characters or fewer) | no, default `0` | Interface to use: its index or name |
| `clients[].add_server_args` | string, as above | no | Overrides `add_server_args` for this client; `""` switches the top-level ones off for it |
| `clients[].add_client_args` | string, as above | no | Overrides `add_client_args` for this client; `""` switches the top-level ones off for it |
| `clients[].bandwidth` | integer > 0 | no | Overrides `bandwidth` for this client |

## Examples

Two Linux loads measuring against one server, with the defaults for
everything optional.

```yaml
components:
  - name: iperf-loads
    type: iperf
    metadata:
      run_duration: 300.0
      iperf_paths:
        linux: /usr/bin/iperf3
      servers:
        - hostname: load8
          port_range_start: 6201
          clients:
            - hostname: load5   # port 6201
            - hostname: load6   # port 6202
```

A mixed Linux and Windows network with a version check, a default bitrate, and
one client that overrides it.

```yaml
components:
  - name: iperf-scada
    type: iperf
    metadata:
      run_duration: 300.0
      iperf_version: "3.15"
      verify_execution: true
      collect_netstat_info: true
      iperf_paths:
        linux: /usr/bin/iperf3
        windows: /iperf-3.15-windows/iperf3.exe
      bandwidth: 200000
      add_client_args: --omit 2
      servers:
        - hostname: control-scada   # Windows
          port_range_start: 6401
          clients:
            - hostname: load5
            - hostname: gen2
              bandwidth: 1000000
        - hostname: load6
          port_range_start: 6501
          clients:
            - hostname: load8
```

rperf, only to generate background traffic (no results are collected).

```yaml
components:
  - name: rperf-traffic
    type: iperf
    metadata:
      run_duration: 600.0
      use_rperf: true
      iperf_paths:
        linux: /usr/local/bin/rperf
      bandwidth: 5000000
      servers:
        - hostname: load8
          port_range_start: 5199
          clients:
            - hostname: load5
            - hostname: load6
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Filebeat

phenix reads `filebeat.inputs` from the component metadata (this component
ignores it). Add this block to ship the result files to Elasticsearch.

```yaml
metadata:
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

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `server X: port N for client Y is already used by server Z` | Two clients would get the same port. Space the `port_range_start` values of servers at least as far apart as their client lists are long. |
| `server X: port N for client Y is too high (its client port M must be <= 65535)` | The client binds to the server port plus `client_port_offset`. Lower `port_range_start` or the offset. |
| `unknown os_type "" for <vm> (hardware.os_type must be linux or windows)` | Set `hardware.os_type` on that node in the topology. |
| `interface eth9 does not exist on node srv` | An `interface` name is not on that node. Use an interface name or index from the topology. |
| `servers listed more than once: a` or `clients listed more than once: a` | Merge the entries; each VM appears once as a server, and once per server as a client. |
| `<vm> is linux, but iperf_paths.linux is not set` | Add the `iperf_paths` entry for that VM's OS. |
| `iperf hosts not in the topology: a, b` | A `hostname` in `servers` or `clients` does not match any node's `general.hostname`. |
| `iperf not in output for VM <uuid> (path=...)` | The executable at that path did not print iperf's version. Check `iperf_paths` and that the file is on the VM. |
| `incorrect iperf version for VM <uuid>, expected 3.15 (path=...)` | The VM's iperf3 is another version. Install the right one, fix `iperf_version`, or turn off `verify_execution`. |
| `failed to execute command '<exe> --version' with filter 'iperf=1 os=linux'` | The version command printed nothing, exited nonzero, or a VM did not answer in time. Check the path, that the VM is running, and that miniccc is up. |
| `run_duration: Input should be less than or equal to 86395` | iperf3 rejects `--time` or `--idle-timeout` above 86400 seconds. Use a shorter run. |
| `add_client_args: String should match pattern ...` or `... --json-stream is not supported ...` | `add_server_args` and `add_client_args` (top level or per client) take only the characters in the field table, so no quotes, `;`, `$`, `|`, `#` or backslashes. |
| `error field set for iperf data from '<file>': <error>` | iperf reported a failure. Usually a client could not reach its server (server not up yet: raise `server_startup_delay`; or the port is in use), or `stop` ran before the clients finished (see [Limitations](#limitations)). Check the `*.log` files next to it. |
| `['/iperf_client-data_client-<c>_server-<s>.json'] not found in VM <c>` (at `stop`) | The client never wrote its results: it did not start, or exited at once. Read `/iperf_client-log_client-<c>_server-<s>.log` on the VM. `some option you are trying to set is server only` there means iperf3 is older than 3.10. |
| `failed to read iperf data from '<file>': ...` | A `*.json` in the run folder is empty or cut off, typically because a client was killed before it wrote its results. Make sure the run lasts at least `run_duration`. |

## Limitations

- Something else must keep the run going for at least `run_duration` before
  `stop`: the clients run in the background and `start` returns at once, so
  `stop` would begin too early and truncate the results or leave an `error`
  field in the client JSON, which fails the stage. Put a component that blocks
  in its `start` (a `disruption` does) in the same run.
- In the `stop` stage, list `iperf` before `collector`.
- rperf results are not processed or ingested, and `add_*_args` are not passed
  to rperf.
- Each server and client uses one interface (`interface`), so a server on
  several VLANs is measured on only one of them.
- Debug logs (`iperf_*-log_*.log`) are only written on Linux VMs.
- Linux iperf3 processes are found and killed through the PID files iperf3
  writes (`iperf_*-pid_*.pid`; the lookup runs as a script sent over cc, kept in
  /tmp/miniccc/files), so an iperf3 you started yourself is left
  alone. Windows iperf3 is killed through miniccc instead, which only knows
  the processes it started (so not after miniccc restarts); rperf has no PID
  file and is killed by name.
- iperf3 3.15 to 3.22 are supported. `--json-stream` (3.17+) is rejected in
  `add_*_args`, since `stop` reads each result file as one JSON document.
- Histograms read the RTT from the first stream of each interval. iperf3 builds
  that do not report it (for example some Windows builds) fail `stop` with
  `KeyError: 'rtt'`; set `create_histogram: false` for those.
