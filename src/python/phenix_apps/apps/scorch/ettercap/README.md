# Ettercap Component

```
type: ettercap
exe:  phenix-scorch-component-ettercap
```

It is assumed that the `ettercap` executable is already present in VMs this
component is configured to interact with and is in the `PATH`.

> NOTE: currently this component does not (yet) support the use of Ettercap
> filters.

## Metadata Options

```yaml
metadata:
  vms:
    - hostname: <vm hostname as defined in the topology>
      iface: <name of interface in VM to use for MITM>
      method: <ettercap MITM method> # not required, defaults to `arp`
      targets: <string of TARGET definitions recognized by ettercap>
```

The resulting `ettercap` command for a VM will look like the following:

```shell
ettercap -Tq -i {iface} -M {method} {targets}
```

## Example Configuration

```yaml
components:
  - name: mitm
    type: ettercap
    metadata:
      vms:
        - hostname: attacker
          iface: eth0
          method: arp
          targets: /10.1.2.2/10.1.2.3/ /10.1.2.10/10.1.2.254/
```
