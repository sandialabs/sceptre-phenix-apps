# Snort

```
type: snort
exe:  phenix-scorch-component-snort
```

Runs [Snort](https://www.snort.org/) as an IDS in one VM (the "detector").
`configure` copies a config/rules set and an optional setup script into the VM
and brings the sniff interface up; `start` clears `/var/log/snort` and launches
`snort -i <iface> -c /etc/snort/snort.conf` in the background; `stop` waits,
sends `pkill -INT snort`, and pulls back `alert`, `snort.log` and
`snort.stats` (converting the stats to `snort-stats.jsonl`); `cleanup` deletes
the logs in the VM.

Snort and its config must already be installed in the detector VM; this
component only places the per-experiment config/rules and runs it.

## Metadata Options

```yaml
metadata:
  hostname: detector      # VM to run Snort in; defaults to `detector`
  interface: eth0    # interface to sniff; defaults to `eth0`
  waitDuration: 30        # seconds to run before stopping; defaults to 30
  configs:                # files copied into the VM at configure
    - src: <path on the phenix server>
      dst: <path in the VM>
      name: <optional label>
  scripts:
    configSnort:          # optional setup script, run once at configure
      executor: <interpreter, e.g. bash>
      script: <path on the phenix server>
```

Every field is validated before the stage runs; a bad value fails the stage.
`hostname`, `interface`, the file paths and the `executor` are restricted
to safe characters because they are used in minimega commands. Check a config before an experiment without running it:
`phenix-scorch-validate scenario.yaml`.

## Examples

A detector with a config, one rules file and a setup script:

```yaml
components:
  - name: snort
    type: snort
    metadata:
      hostname: detector
      interface: eth0
      waitDuration: 30
      configs:
        - name: snort
          src: /phenix/topologies/snort-test/configs/snort.conf
          dst: /etc/snort/snort.conf
        - name: emotet
          src: /phenix/topologies/snort-test/configs/emotet.rules
          dst: /etc/snort/rules/emotet.rules
      scripts:
        configSnort:
          executor: bash
          script: /phenix/topologies/snort-test/scripts/configure-snort.sh
```

The minimum: just a config, on the defaults:

```yaml
components:
  - name: snort
    type: snort
    metadata:
      configs:
        - src: /phenix/topologies/snort-test/configs/snort.conf
          dst: /etc/snort/snort.conf
```

## Troubleshooting

| Message | Cause |
| --- | --- |
| `hostname: ...` | the detector hostname is malformed |
| `interface: ...` | the interface name is missing or malformed |
| `waitDuration: Input should be greater than or equal to 0` | a negative wait |
| `configs.0.src: ...` / `configs.0.dst: ...` | a config path is missing or has characters outside a file path |
| `scripts.configSnort.executor: ...` | the executor is missing or malformed |
