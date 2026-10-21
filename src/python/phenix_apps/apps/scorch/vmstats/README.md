# vmstats Component

Collects resource utilization statistics from Linux VMs in the experiment, using the `vmstat` command.

```
type:   vmstats
exe:    phenix-scorch-component-vmstats
stages: start, stop
```

| Stage | What it does |
|---|---|
| `start` | Tags each chosen VM `vmstat=1` and starts `vmstat -n -t <pollPeriod>` in the background in each Linux VM, appending to `/vmstat.out` in the VM. Does not wait for `vmstat` to start or finish; the stage ends once the commands are sent. |
| `stop` | Stops `vmstat` on each VM, waits `stopWait` seconds, copies each VM's `/vmstat.out` back, deletes it from the VMs, and writes every sample to `vm_stats.jsonl`. |

List it in both `start` and `stop` of the run. It does not need
`background: true`: `start` does not wait for `vmstat`.

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
<vm>.out                  each VM's raw vmstat output
vm_stats.jsonl            one JSON object per VM per sample (fields below)
<stage>-<UTC time>.json   the SCORCH status files (logs, and the error on failure)
```

## Before you start

- **Linux VMs with `vmstat` on the path.** Without `vms`, every VM
  whose topology `hardware.os_type` is `linux`, `centos`, `rhel`, `vyos` or `vyatta` is used. A VM without `os_type` counts as `linux`, as phenix core defaults it.
  Commands only reach VMs whose miniccc agent reports Linux, so a non-Linux VM listed
  in `vms` collects nothing and fails `stop`.
- **miniccc must be running in the VMs.**

## Metadata

| Field | Type | Default | Meaning |
|---|---|---|---|
| `pollPeriod` | whole number > 0 | `1` | Seconds between samples (vmstat's delay) |
| `stopWait` | seconds, 0 or more | `5` | Time to wait after stopping vmstat, before collecting |
| `vms` | non-empty list of VM names | every Linux VM | VMs to sample. Shorthand such as `load[1-5]` expands to `load1` ... `load5`. Names have no whitespace, quotes, `/`, `#` or `\` |
| `filebeat.inputs` | list | | Filebeat inputs for phenix (see the example) |

## Examples

```yaml
components:
  - name: vmstats
    type: vmstats
    metadata:
      pollPeriod: 1
      vms:
        - power-provider
        - attacker
        - load[5-6]
      filebeat.inputs:
        - type: filestream
          id: vmstats-input
          enabled: true
          paths:
            - vm_stats.jsonl
          parsers:
            - ndjson:
                target: vmstats
                add_error_key: true
          processors:
            - timestamp:
                field: vmstats.UTC
                layouts:
                  - "2006-01-02 15:04:05"
                test:
                  - "2024-02-29 17:49:29"
            # copied to @timestamp above, so no need to keep it
            - drop_fields:
                fields:
                  - vmstats.UTC
                  - input.type   # always "filestream"
runs:
  - configure: []
    start: [vmstats]
    stop: [vmstats]
    cleanup: []
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `no vmstat.out from N VM(s) (the others were collected): <vms>` | Those VMs produced no output: not Linux (as miniccc reports it), no `vmstat`, miniccc not running, or the VM was down. The other VMs' samples are in `vm_stats.jsonl`. |
| warning `skipped N unreadable line(s) from <vm>` | Lines that are not samples, usually the last one cut short when vmstat was stopped. A few are normal. |
| Elasticsearch documents have no timestamp | The VM is not on UTC, so the timestamp column has another name. Set the VMs to UTC, or change `vmstats.UTC` in the Filebeat input. |
| `pollPeriod: Input should be greater than 0` | `pollPeriod` must be a whole number of seconds, 1 or more. |

## Limitations

- On a VM whose `vmstat` has no `-t` (procps before 3.3, such as VyOS
  routers), the component adds the timestamps itself, in UTC, using `stdbuf`
  when the VM has it. Without `stdbuf`, vmstat may buffer its output and
  several samples can get the same timestamp. This path is untested on a real
  VyOS image.

## Record fields

Each `vm_stats.jsonl` record has `vm_name`, the sample time under the timezone's
name (`UTC` on a VM set to UTC), and vmstat's columns. With the Filebeat input
above they are nested under `vmstats.*` in Elasticsearch, for example
`vmstats.r`.

References:
- https://www.redhat.com/sysadmin/linux-commands-vmstat
- https://linux.die.net/man/8/vmstat

Data collected:
- Procs
    - r: The number of runnable processes (running or waiting for run times)
    - b: The number of processes in uninterruptible sleep.
- Memory
    - swpd: the amount of virtual memory used.
    - free: the amount of idle memory
    - buff: the amount of memory used as buffers
    - cache: the amount of memory used as cache.
- Swap
    - si: Amount of memory swapped in from disk (/s).
    - so: Amount of memory swapped to a block device (/s).
- IO
    - bi: Blocks received from a block device (blocks/s).
    - bo: Blocks sent to a block device (blocks/s).
- System
    - in: The number of interrupts per second, including the clock.
    - cs: The number of context switches per second.
- CPU
    - These are percentages of total CPU time.
    - us: Time spent running non-kernel code. (user time, including nice time)
    - sy: Time spent running kernel code. (system time)
    - id: Time spent idle. Prior to Linux 2.5.41, this includes IO-wait time.
    - wa: Time spent waiting for IO.  Before Linux 2.5.41, included in idle.
    - st: Time stolen from a virtual machine.  Prior to Linux 2.6.11, unknown.
