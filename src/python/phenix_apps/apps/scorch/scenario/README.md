# scenario Component

Orchestrates and executes disruption scenarios for cyber-physical experiments.

```
type:   scenario
exe:    phenix-scorch-component-scenario
stages: configure, start, cleanup
```

## Metadata Options

```yaml
metadata:
  current_scenario: <string>  # (REQUIRED) scenario names: baseline, dos, cyber_physical, physical
  permutation: <integer>  # (Optional) Permutation number. This is used by the collector Scorch component, and is REQUIRED if that component is enabled.
  run_duration: <float>  # (REQUIRED) Total execution time of the scenario, in seconds
  dos:  # Denial of Service (DoS) scenario configuration
    attack_duration: <float>  # (REQUIRED) How long the DoS attack should run for, in seconds
    start_delay: <float>  # (REQUIRED) Seconds to wait before beginning attack. Set to 0.0 to begin immediately.
    attacker:
      hostname: <string>  # (REQUIRED) Name of VM running Kali Linux
      interface: <string>  # (Optional) Name of interface launch attack from. Default: "eth0"
      script_path: <string>  # (REQUIRED) Absolute path to DoS attack script (dos.py)
      results_path: <string>  # (REQUIRED) Absolute path to attack results JSON file
    targets:
      - hostname: <string>  # (REQUIRED) Hostname of target host VM in phenix topology
        interface: <string>  # (Optional) Name of interface to use to launch the attack on this particular target. Default: "eth0"
  physical:
    start_delay: <float>
    opc_hostname: <string>  # (REQUIRED) Hostname of OPC server VM in the topology. Required if the scenario will be sending commands via OPC.
    opc_port: <integer>  # (Optional) OPC-UA port for scenario script to use. Default: 4840
    script_path: <string>
    results_path: <string>
    scenario_path: <string>
    log_path: <string>
    python_path: <string>
```

## Example Configuration

```yaml
components:
  - name: scenario-example
    type: scenario
    metadata:
      # scenario names: baseline, dos, cyber_physical, physical
      current_scenario: baseline
      permutation: 0
      run_duration: 300.0
      dos:
        attack_duration: 120.0  # seconds to run attack for
        start_delay: 60.0  # seconds to wait until launching attack
        attacker:
          hostname: attacker  # hostname of box running Kali
          interface: eth0  # defaults to "eth0"
          script_path: /root/dos.py
          results_path: /root/attacker_results.json
        targets:
          - hostname: load5
            interface: eth0
          - hostname: load6
            interface: eth0
      physical:
        # NOTE: this uses settings from the dos scenario
        start_delay: 60.0  # seconds to wait until beginning disruption
        opc_hostname: control-scada
        opc_port: 4840  # optional, defaults to 4840
        script_path: /harmonie_scada.py
        results_path: /scenario_results.json
        scenario_path: /cyber_physical_2024.json
        log_path: /harmonie_scada.log
        python_path: /users/wwuser/appdata/local/programs/python/python38/python.exe
```
