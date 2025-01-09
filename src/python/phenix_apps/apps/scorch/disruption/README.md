# disruption Component

Orchestrates and executes disruption scenarios for cyber-physical experiments.

```
type:   disruption
exe:    phenix-scorch-component-disruption
stages: configure, start, cleanup
```

## Metadata Options

```yaml
metadata:
  current_disruption: <string>  # (REQUIRED) disruption names: baseline, dos, cyber_physical, physical
  permutation: <integer>  # (Optional) Permutation number. This is used by the collector Scorch component, and is REQUIRED if that component is enabled.
  run_duration: <float>  # (REQUIRED) Total execution time of the disruption, in seconds
  dos:  # Denial of Service (DoS) disruption configuration
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
    opc_hostname: <string>  # (REQUIRED) Hostname of OPC server VM in the topology. Required if the disruption will be sending commands via OPC.
    opc_port: <integer>  # (Optional) OPC-UA port for disruption script to use. Default: 4840
    script_path: <string>
    results_path: <string>
    scenario_path: <string>
    log_path: <string>
    python_path: <string>
```

## Example Configuration

```yaml
components:
  - name: disruption-example
    type: disruption
    metadata:
      # disruption names: baseline, dos, cyber_physical, physical
      current_disruption: baseline
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
        # NOTE: this uses settings from the dos disruption
        start_delay: 60.0  # seconds to wait until beginning disruption
        opc_hostname: control-scada
        opc_port: 4840  # optional, defaults to 4840
        script_path: /harmonie_scada.py
        results_path: /scenario_results.json
        scenario_path: /cyber_physical_2024.json
        log_path: /harmonie_scada.log
        python_path: /users/wwuser/appdata/local/programs/python/python38/python.exe
```

## Notes and Considerations
 * for a cyber_physical experiment, if overall run_time is shorter than combined dos.start_delay plus dos.attack_duration or physical.start_delay plus 5 minutes (whichever is longer), then phenix will fail because dos did not have enough time to export results or physical is not finished.
 * for a cyber_physical experiment, if dos.start_delay is longer than the overall run_time, there is no check shorten dos.start_delay in relation to dos.attack_duration. There is only a check to shorten dos.attack_duration.
 * for a cyber_physical/dos/physical experiment, if combined dos.start_delay plus dos.attack_duration or physical.start_delay plus 5 minutes exactly equal the overall run_duration, then phenix will fail because dos and physical will not have enough time to wrap up.
 * for a cyber_physical/physical experiment, there is no check to see if physical.start_delay is larger than the overall run_duration
 * for a cyber_physical/physical experiment, there is hard requirement that run_duration must be slightly longer than the physical.start_delay plus the physical run duration or the experiment will fail. Physical run duration is varied and cannot be extended or shortened from this configuration.
 * for a cyber_physical/dos experiment, if the dos.attack_duration is smaller than the time it takes to execute and run the command, few seconds or zero, the experiment may fail because the command was canceled or not run properly. Default values for dos.attack_duration may be needed for small values. This may also require a default run_duration if that is very small as well.
