# vmstats Component

Collects resource utilization statistics from VMs in the experiment, using the `vmstats` command.

```
type:   vmstats
exe:    phenix-scorch-component-vmstats
stages: start, stop
```

## Notes
- Statistics collected include memory usage, CPU times, IO counters, and process counts, among other statistics. See the section at the end of this README for a complete list.
- Only Linux hosts are supported, and the `vmstat` command must be available and on the path.
- Routers (VyOS) are not currently supported, since it uses a older version of `vmstat` that is missing arguments used by this component. If this functionality is needed, it shouldn't be too much work to fix this compatibility issue.
- Compatible `os_type` (from phenix topology): `linux`, `centos`, `rhel`
- Stats are written to the file `/vmstat.out` in the VM, which is a plain-text file. During the `stop` stage, this file is transferred to the host and parsed. The results from all hosts are combined and written to `vm_stats.jsonl` in JSON lines format (one JSON object per line). This file is needed for filebeat to ingest into Elasticsearch.


## Metadata Options

```yaml
metadata:
  pollPeriod: <integer>  # (Optional) Rate at which statistics are sampled ('-t' argument to 'vmstat'). Default: 1 (every second)
  vms: <list of strings>  # (Optional) List of hostnames of VMs to run vmstats on. If empty or unspecified, this is run on all supported hosts in the topology (Linux VMs).
  filebeat.inputs:
    - type: filestream
      id: vmstats-input
      enabled: true
      paths:
        - vm_stats.jsonl
      parsers:
        - ndjson:
            target: "vmstats"
            add_error_key: true
      processors:
        - timestamp:
            field: vmstats.UTC
            layouts:
              - '2006-01-02 15:04:05'
            test:
              - '2024-02-29 17:49:29'
        - drop_fields:
            fields:
              - vmstats.UTC  # this gets parsed and copied to @timestamp, no reason to keep around
              - input.type  # drop 'input.type', since it will always be 'filestream'
```

The `filebeat.inputs` section above can be blindly copied into user's own config and used as-is, or users can choose to change target field names if the ones used above aren't suitable.

## Example Configuration

```yaml
components:
  - name: vmstats-example
    type: vmstats
    metadata:
      pollPeriod: 1
      vms:
        - power-provider
        - attacker
        - load5
        - gen2
        - br75
      filebeat.inputs:
        - type: filestream
          id: vmstats-input
          enabled: true
          paths:
            - vm_stats.jsonl
          parsers:
            - ndjson:
                target: "vmstats"
                add_error_key: true
          processors:
            - timestamp:
                field: vmstats.UTC
                layouts:
                  - '2006-01-02 15:04:05'
                test:
                  - '2024-02-29 17:49:29'
            - drop_fields:
                fields:
                  - vmstats.UTC
                  - input.type
```

## vmstats Data Fields

These are nested under `vmstats.*` in the filebeat-ingested data in Elasticsearch, e.g. `vmstats.r`.

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
    - inact: the amount of inactive memory. (-a option)
    - active: the amount of active memory. (-a option)
- Swap
    - si: Amount of memory swapped in from disk (/s).
    - so: Amount of memory swapped to a block device (/s).
- IO
    - bi: Blocks received from a block device (blocks/s).
    - bo: Blocks sent to a block device (blocks/s).
- System
    - in: The number of interrupts per second, including the clock.
    - cs: The number of context switcher per second.
- CPU
    - These are percentages of total CPU time.
    - us: Time spent running non-kernel code. (user time, including nice time)
    - sy: Time spent running kernel code. (system time)
    - id: Time spent idle. Prior to Linux 2.5.41, this includes IO-wait time.
    - wa: Time spent waiting for IO.  Before Linux 2.5.41, included in idle.
    - st: Time stolen from a virtual machine.  Prior to Linux 2.6.11, unknown.
