# qos Component

Apply [minimega Quality of Service (QOS)](https://sandia-minimega.github.io/minimega/reference/minimega/?h=qos#qos) effects on network interfaces, including dropping packets (`loss`), delaying packets (`delay`), or limiting bandwidth (`rate`).

```
type:   qos
exe:    phenix-scorch-component-qos
stages: start, stop
```

| Stage | What it does |
|---|---|
| `start` | Applies each entry's loss, delay or rate to its VM interface, and writes what it applied to `qos_values_applied.json`. |
| `stop` | Clears all QoS from every listed VM interface. |

## What you get

In the component's run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
qos_values_applied.json   per hostname: the interface index and the loss, delay and rate applied
<stage>-<UTC time>.json   the SCORCH status files (logs, and the error on failure)
```

The `collector` component copies `qos_values_applied.json` into its results
and the experiment record.

## Before you start

List the component in `start` and `stop` of the run, or the effects stay on
after the run.

## Metadata

Each entry in `vms`:

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `hostname` | hostname | yes | | VM in the topology |
| `interface` | index or name | no | `0` | Interface to degrade: an index into the VM's interfaces, or its name |
| `loss` | number 0 to 99.9 | one of these | | Percentage of arriving packets to drop |
| `variable_loss` | number >= 0 | one of these | | Loss that grows with the run: `variable_loss` x the SCORCH count (iteration). Replaces `loss` when both are set |
| `delay` | duration | one of these | | How long to hold each arriving packet: `100ms`, `1s`, `1m30s`, `.5s` (Go duration syntax); a bare number such as `100` means milliseconds, as in minimega |
| `rate` | number and unit | one of these | | Bandwidth cap: `500 kbit`, `10mbit`, `1 gbit` (units `kbit`, `mbit`, `gbit`). minimega needs a whole number, so `1.5 mbit` is applied as `1500 kbit`, and a rate that is not a whole number of kbit is rejected |

Each entry needs at least one of `loss`, `variable_loss`, `delay` and `rate`.
To apply several effects to one interface, either put them in one entry
(`loss` and `delay`) or list the interface twice.

## Examples

A lossy, slow field network: drop a quarter of what reaches one RTU, delay the
SCADA server's second interface, and cap a relay's bandwidth.

```yaml
components:
  - name: degraded-field
    type: qos
    metadata:
      vms:
        - hostname: rtu-2
          interface: 0
          loss: 25.0
          delay: 1s
        - hostname: scada
          interface: 1
          delay: 100ms
        - hostname: relay-6
          rate: 500 kbit
```

Loss that rises with each iteration of a run: 0 % in count 0, 10 % in count 1,
up to 90 % in count 9. Run it with `count: 10` on the SCORCH run.

```yaml
components:
  - name: rising-loss
    type: qos
    metadata:
      vms:
        - hostname: relay-10
          interface: eth0
          variable_loss: 10.0
```

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `vms.N: Value error, needs one of loss, variable_loss, delay or rate` | The entry has none of them. |
| `vms.N: Value error, rate cannot be combined with loss or delay` | Split the effects across interfaces, or drop the rate. |
| `vms.N.rate: Value error, must be a number and kbit, mbit or gbit, like '500 kbit'` | Use one of those units (`kbps`, `Mb` and so on are not accepted). |
| `vms.N.delay: String should match pattern ...` | Use a Go duration like `100ms` (a bare number means milliseconds), not `100x`. |
| `loss of N for <vm> is not between 0.0 - 99.9 ...` | With `variable_loss`, the count got high enough to pass 99.9 %. Lower `variable_loss` or the number of iterations. |
| `failed to find node "<vm>"` / `interface <name> does not exist on node <vm>` | Check the hostname and interface against the topology. |

## Limitations

- `qos_values_applied.json` is keyed by hostname, so two interfaces of the same
  VM share one record (the last interface wins).
- `stop` clears every QoS setting on each listed interface, including ones made
  by something else.
- Only traffic arriving at the VM is affected: QoS is applied on the host side
  of the VM's tap. To degrade both directions, apply it to the VMs at both ends.
- A rate cannot be combined with loss or delay on the same interface (a limit of
  `tc` as minimega uses it).
- Loss is at most 99.9 %. To cut a link completely, disconnect the interface
  instead (the `mm` component can).
- `interface` defaults to index `0`, which may be the management interface.
