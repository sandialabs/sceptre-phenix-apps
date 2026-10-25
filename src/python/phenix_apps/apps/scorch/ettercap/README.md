# Ettercap Component

```
type: ettercap
exe:  phenix-scorch-component-ettercap
```

Runs [ettercap](https://www.ettercap-project.org/) as a man-in-the-middle in
one or more VMs. For each VM it brings the interface up and launches
`ettercap -Tq -i <iface> -M <method> <targets>` in the background; `stop` kills
it with `pkill ettercap`.

The `ettercap` executable must already be on the `PATH` in every VM this
component targets.

> NOTE: this component does not (yet) support ettercap filters.

## Metadata Options

```yaml
metadata:
  vms:                          # at least one; one MITM per host interface
    - hostname: <vm hostname>   # as defined in the topology
      iface: <interface name>   # interface in the VM to run the MITM on
      targets: <TARGET string>  # ettercap TARGETs, e.g. /10.0.0.1// /10.0.0.2//
      method: <MITM method>     # optional, defaults to `arp`
```

Every field is validated before the stage runs; a bad value fails the stage
rather than reaching the VM. `targets` and `method` are restricted to the
characters ettercap accepts so they cannot carry shell syntax:

- `method` is one of `arp`, `icmp`, `dhcp`, `port`, `ndp`, optionally with an
  argument (`arp:remote,oneway`, `icmp:MAC/IP`, `dhcp:ip_pool/netmask/dns`).
- `targets` is a space-separated list of `/MAC/IPs/PORTs/` triples; empty
  fields match everything (`/10.0.0.1//` is "this IP, any MAC, any port").
  A target cannot start with `-`, so it cannot be read as an ettercap option.

Check a config without running it with `phenix-scorch-validate`.

## Examples

Poison a single host pair:

```yaml
components:
  - name: mitm
    type: ettercap
    metadata:
      vms:
        - hostname: attacker
          iface: eth0
          targets: /10.1.2.2// /10.1.2.3//
```

Two attackers, with an explicit method and an address range:

```yaml
components:
  - name: mitm-multi
    type: ettercap
    metadata:
      vms:
        - hostname: attacker-a
          iface: eth0
          method: arp
          targets: /10.1.2.2/80,443/ /10.1.2.10-20//
        - hostname: attacker-b
          iface: eth1
          targets: /10.1.3.2//
```

The resulting command for the first VM above is:

```shell
ettercap -Tq -i eth0 -M arp /10.1.2.2// /10.1.2.3//
```

## Troubleshooting

| Message | Cause |
| --- | --- |
| `vms: Field required` | no `vms` list was given |
| `vms: List should have at least 1 item` | `vms` is empty |
| `vms.0.iface: ...` | the interface name is missing or malformed |
| `vms.0.targets: String should match pattern ...` | `targets` is empty or contains characters outside `/`, digits, hex, `.`, `:`, `,`, `-` and single spaces, or a target starts with `-` |
| `vms.0.method: String should match pattern ...` | `method` is not one of `arp`/`icmp`/`dhcp`/`port`/`ndp` |
| `vms: ettercap started more than once on: <host> <iface>` | the same host interface appears twice |
