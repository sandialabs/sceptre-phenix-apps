# disruption Component

Orchestrates and executes disruption scenarios for cyber-physical experiments:
a quiet baseline, a denial-of-service (DoS) attack from an attacker VM, a
physical disruption driven over OPC-UA, or both at once.

```
type:   disruption
exe:    phenix-scorch-component-disruption
stages: configure, start, cleanup
```

| Disruption | What `start` does |
|---|---|
| `baseline` | Sleeps for `run_duration`, recording start and stop times. |
| `dos` | Runs the DoS script on the attacker and waits for it, then sleeps out the rest of `run_duration`. |
| `physical` | Waits `physical.start_delay`, runs the physical scenario script on the OPC VM, then sleeps out the rest. |
| `cyber_physical` | Starts the DoS script in the background, then runs the physical disruption as above. Nothing waits for the DoS to finish; it is killed at the end. |

| Stage | What it does |
|---|---|
| `configure` | For `dos` and `cyber_physical` only. Checks the attacker and every target VM are running, kills stale `hping3` and DoS script processes on the attacker, and takes down every attacker interface except the attack interface and `MGMT`. On the first loop and first count only (`loop < 2` and `count < 2`), it also runs `hping3 --version` and `<script_path> --help` on the attacker to check both are installed; later loops and counts skip that check. |
| `start` | Runs the disruption (table above), then collects results. Blocks for about `run_duration`. |
| `cleanup` | For `dos` and `cyber_physical`: kills leftover processes, deletes the attacker's results file, and brings the downed interfaces back up. For `physical` and `cyber_physical`: kills `python.exe` on the OPC VM and deletes only `results_path` and `log_path` there. `baseline` does nothing. |

## What you get

In the component's run folder
(`<files>/scorch/run-<run>/<component name>/loop-<loop>-count-<count>/`):

```
disruption_start_time.txt   ISO UTC; start is rounded up to the next whole second
disruption_stop_time.txt    ISO UTC
<attacker results_path>     dos and cyber_physical, pulled back by file name
<attacker script_path>      dos and cyber_physical, pulled back by file name
<physical script_path>      physical and cyber_physical, pulled back by file name
<physical results_path>
<physical scenario_path>
<physical log_path>
```

The `pcap` and `collector` components read this component's metadata (and the
collector reads these files) to line up their output with the disruption.

## Before you start

- **The VMs must be running with miniccc.** `dos` needs the attacker and every
  target; `physical` needs the OPC VM. Commands reach them through miniccc.
- **The attacker is Linux** (Kali) unless `attacker.os_type` is `windows`. It
  needs `hping3` and an executable DoS script at `attacker.script_path`, which
  is called with `--wait-for`, `--run-for`, `--target-ips`, `--interface` and
  `--results-file`, then any `attacker.args`. `os_type` picks how processes are
  killed (`pkill` or `taskkill`, so on Windows `hping3.exe` and the script's
  file name), how interfaces go down and up (`ip link` or `netsh`) and how the
  results file is deleted.
- **The OPC VM is Windows**, running the physical scenario Python script. The
  OS is fixed to Windows: `python.exe` is killed with `taskkill` and result
  files are deleted with Windows commands. Set `python_path` to the real
  Python binary: running the script directly exits with code -1 under miniccc.

## Metadata

A run can keep both `dos` and `physical` blocks and switch only
`current_disruption`, but every block present is validated, used or not.
Unknown top-level keys are kept so other components (such as `collector`) can
read their own.

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `current_disruption` | string | yes | | `baseline`, `dos`, `physical` or `cyber_physical` |
| `run_duration` | finite float > 0 | yes | | Total length of the disruption, in seconds |
| `permutation` | integer >= 0 | no | | Required by the `collector` component |
| `dos` | block | for `dos` and `cyber_physical` | | See below |
| `physical` | block | for `physical` and `cyber_physical` | | See below |

`dos` block:

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `attack_duration` | float > 0 | yes | | How long the attack runs, in seconds |
| `start_delay` | float >= 0 | yes | | Seconds the script waits before attacking |
| `wrapup` | float >= 0 | no | `60.0` | Seconds the attack must finish before `run_duration` ends, so results can be collected |
| `attacker.hostname` | hostname (2-63 letters, digits, interior hyphens) | yes | | Attacker VM in the topology (Kali Linux) |
| `attacker.interface` | Linux interface name (up to 15 characters) | no | `eth0` | Interface the attack leaves from |
| `attacker.script_path` | file path | yes | | Absolute path to the DoS script (`dos.py`) on the attacker |
| `attacker.args` | string | no | empty | Extra arguments appended to the script's command line |
| `attacker.results_path` | file path | yes | | Where the script writes its JSON results |
| `attacker.os_type` | `linux` or `windows` | no | `linux` | OS of the attacker VM |
| `wait_margin` | float >= 0 | no | `5.0` | Seconds past `start_delay` plus the attack before the script counts as hung |
| `targets` | list, at least one | yes | | Hosts to attack |
| `targets[].hostname` | hostname | yes | | Target VM in the topology |
| `targets[].interface` | Linux interface name | no | `eth0` | Interface whose address is attacked |

`physical` block:

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `start_delay` | float >= 0 | yes | | Seconds to wait before the physical disruption; must be less than `run_duration` |
| `opc_hostname` | hostname | yes | | VM running the OPC-UA server; the script runs there too |
| `opc_port` | integer 1-65535 | no | `4840` | OPC-UA port |
| `script_path` | file path | yes | | Physical scenario script on the OPC VM |
| `results_path` | file path | yes | | Where the script writes its JSON results |
| `scenario_path` | file path | yes | | Scenario file the script replays |
| `log_path` | file path | yes | | Script log file |
| `timeout_margin` | float >= 0 | no | `15.0` | Seconds past `start_delay` the script may run |
| `python_path` | file path | no | `/users/wwuser/appdata/local/programs/python/python38/python.exe` | Python binary on the OPC VM. miniccc cannot run the script directly. |

A file path is Linux or Windows style with forward slashes (`/root/dos.py`,
`C:/tools/dos.exe`) and no spaces, quotes or shell characters, since it is
placed in commands unquoted.

### Timing

- The DoS attack must finish `dos.wrapup` seconds (default 60) before
  `run_duration` ends. It runs for `attack_duration`, cut to
  `run_duration - wrapup - 1 - dos.start_delay` if that is shorter. A
  `dos.start_delay` that leaves no time at all is rejected.
- For `dos`, the component waits for `dos.start_delay` plus the attack time
  plus `dos.wait_margin` before treating the script as hung.
- For `cyber_physical`, the DoS script runs in the background and nothing
  waits for it. It is killed at the end of `start`, after the stop time is
  recorded.
- The physical script gets a timeout of `physical.start_delay +
  physical.timeout_margin` seconds. If that is more than `run_duration`, the
  timeout is `run_duration - 1`
  instead. A timeout of zero or less is rejected. The script must finish inside
  the timeout, and its run time comes from the scenario file, not from this
  config.

## Examples

Baseline: record a quiet five minutes.

```yaml
components:
  - name: baseline
    type: disruption
    metadata:
      current_disruption: baseline
      permutation: 0
      run_duration: 300.0
```

DoS: attack two loads for two minutes, starting a minute in.

```yaml
components:
  - name: dos-loads
    type: disruption
    metadata:
      current_disruption: dos
      permutation: 1
      run_duration: 300.0
      dos:
        attack_duration: 120.0
        start_delay: 60.0
        attacker:
          hostname: attacker
          interface: eth0
          script_path: /root/dos.py
          results_path: /root/attacker_results.json
        targets:
          - hostname: load5
          - hostname: load6
            interface: eth1
```

Physical: replay a scenario against the SCADA server a minute in.

```yaml
components:
  - name: physical-scenario
    type: disruption
    metadata:
      current_disruption: physical
      permutation: 2
      run_duration: 300.0
      physical:
        start_delay: 60.0
        opc_hostname: control-scada
        script_path: /harmonie_scada.py
        results_path: /scenario_results.json
        scenario_path: /cyber_physical_2024.json
        log_path: /harmonie_scada.log
```

Cyber-physical: the DoS runs in the background while the physical scenario
plays out. A run of several permutations usually keeps both blocks in every
entry and changes only `current_disruption`, as here.

```yaml
components:
  - name: cyber-physical
    type: disruption
    metadata:
      current_disruption: cyber_physical
      permutation: 3
      run_duration: 400.0
      dos:
        attack_duration: 120.0
        start_delay: 66.0
        attacker:
          hostname: attacker
          script_path: /root/dos.py
          results_path: /root/attacker_results.json
        targets:
          - hostname: load5
          - hostname: load6
      physical:
        start_delay: 60.0
        opc_hostname: control-scada
        opc_port: 4840
        script_path: /harmonie_scada.py
        results_path: /scenario_results.json
        scenario_path: /cyber_physical_2024.json
        log_path: /harmonie_scada.log
        python_path: /users/wwuser/appdata/local/programs/python/python38/python.exe
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `VM isn't running (vm name: X)` | The attacker or a target is not running. Start it, or fix the hostname. |
| `failed to run 'hping3 --version'` (followed by `exitcode`, `stdout`, `stderr`) | `hping3` is missing on the attacker, or miniccc cannot run it. Install it in the image. |
| `failed to run '<script_path> --help'` | The DoS script is missing or not executable at `attacker.script_path`. Fix the path or its permissions. |
| `node X does not exist` | A `targets[].hostname` is not in the topology. |
| `interface eth1 does not exist on node load6` | A target's `interface` is not on that node. Use an interface name from the topology. |
| `dos.start_delay (X) leaves no time to attack: run_duration must exceed start_delay + 61 seconds` | Raise `run_duration` or lower `dos.start_delay`. |
| `physical.start_delay (X) must be less than run_duration (Y)` | Lower `physical.start_delay` or raise `run_duration`. |
| `'dos' needs a dos block` (or `'physical' needs a physical block`) | Add the block the current disruption uses. `cyber_physical` needs both. |
| `Failed to run 'dos' disruption: no stdout from command` | The DoS script printed nothing, so it likely failed. Run it by hand on the attacker. |
| `Failed to run 'cyber_physical' disruption: no stdout from command` | The physical script printed nothing. Raised for plain `physical` too, with this same text. Check `python_path`, `script_path` and `scenario_path`, and the script's log. Exit code -1 means the script was run without `python_path`. |
| `physical disruption did not run: scenario_duration=N` | The results file shows the scenario ran for 1 second or less. Check the OPC server and `physical.log_path`. |
| `N disruption stage(s) failed: '<name>': <status>; ...` | Non-OPC stages in the physical results reported failure; every failed stage is listed. Read the results file and log. |
| `error receiving file ... not found in VM ...` | A file to collect (`results_path`, `script_path`, `scenario_path` or `log_path`) is not on the VM. The script may have failed before writing it. Fix the path or the script. |

## Limitations

- `start` blocks for about `run_duration`; size the `start` stage around it.
- `collector` needs `permutation` and must be listed last in `stop`.
- The physical disruption's run time comes from its scenario file, so
  `run_duration` must be long enough by hand: `physical.start_delay` plus the
  scenario plus a few seconds to collect results.
- A DoS attack that would run under 5 seconds (a short `dos.attack_duration`,
  or one cut short by `run_duration`) may end before the script has started
  properly, and the run then fails. The metadata check logs a warning.
