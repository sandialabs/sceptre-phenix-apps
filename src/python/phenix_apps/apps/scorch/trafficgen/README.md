# Traffic Generator

Copies traffic scripts into VMs, runs a traffic server and optional background
and malware clients against it, then stops and removes them.

```
type:   trafficgen
exe:    phenix-scorch-component-trafficgen
stages: configure, start, stop, cleanup
```

| Stage | What it does |
|---|---|
| `configure` | Copies each script to the root (`/`) of the VM that runs it. |
| `start` | Per target: starts the server script, starts each client against the server's IP, then waits `duration + 5` seconds. |
| `stop` | Kills the scripts with `pkill -f <script name>`. |
| `cleanup` | Deletes the copied scripts from the VMs. |

## Examples

Background traffic against one server, using every default.

```yaml
components:
  - name: traffic-basic
    type: trafficgen
    metadata:
      scripts:
        trafficServer: /phenix/topologies/trafficgen-test/scripts/traffic-server.py
        backgroundGen: /phenix/topologies/trafficgen-test/scripts/background-gen.py
      targets:
        - backgroundClient: {}   # traffic-server, IF0, 5 seconds
```

Background and malware clients, with every option set.

```yaml
components:
  - name: traffic-full
    type: trafficgen
    metadata:
      scripts:
        trafficServer: /phenix/topologies/trafficgen-test/scripts/traffic-server.py
        backgroundGen: /phenix/topologies/trafficgen-test/scripts/background-gen.py
        malwareGen: /phenix/topologies/trafficgen-test/scripts/malware-gen.py
      targets:
        - hostname: traffic-server
          interface: IF0
          duration: 30
          backgroundClient:
            hostname: background-gen
            rate: 10000
            probability: 0.01
          malwareClient:
            hostname: malware-gen
            rate: 20
            probability: 1.25
```

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `scripts.trafficServer` | path | yes | | Script run on each target. |
| `scripts.backgroundGen` | path | with a `backgroundClient` | | Script run on background clients. |
| `scripts.malwareGen` | path | with a `malwareClient` | | Script run on malware clients. |
| `targets` | list | yes | | At least one target. Targets run one after another. |
| `targets[].hostname` | hostname | no | `traffic-server` | VM running the server script. |
| `targets[].interface` | name | no | `IF0` | Interface whose IP the clients connect to. |
| `targets[].duration` | whole seconds | no | `5` | Passed to clients as `--duration`. |
| `targets[].backgroundClient.hostname` | hostname | no | `background-gen` | VM running the background script. |
| `targets[].backgroundClient.rate` | integer | no | `10000` | Passed as `--rate`. |
| `targets[].backgroundClient.probability` | number | no | `0.01` | Passed as `--probability`. |
| `targets[].malwareClient.hostname` | hostname | no | `malware-gen` | VM running the malware script. |
| `targets[].malwareClient.rate` | integer | no | `20` | Passed as `--rate`. |
| `targets[].malwareClient.probability` | number | no | `1.25` | Passed as `--probability`. |

Script paths may use letters, digits and `_ . / + @ -` only. Unknown keys in
`scripts` and the target blocks are ignored with a warning.

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `targets: List should have at least 1 item` | Add a target. |
| `scripts.trafficServer: Field required` | Add the server script path. |
| `scripts.backgroundGen: required when a target has backgroundClient` | Set the script, or drop the client. Same for `malwareGen` and `malwareClient`. |
| `...scripts.trafficServer: String should match pattern` | The path has a character outside the allowed set (spaces, quotes, `;`). |
| `... hostname: ...` | The hostname has characters outside letters, digits, `.`, `_` and `-`, or is under two characters. |
