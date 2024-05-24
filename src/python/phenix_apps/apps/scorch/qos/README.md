# qos Component

Apply Quality of Service (QoS) effects on network interfaces, including dropping packets (`loss`), delaying packets (`delay`), or limiting bandwidth (`rate`).

```
type:   qos
exe:    phenix-scorch-component-qos
stages: start, stop
```

## Notes

- Due to limitations of the underlying tool used by minimega, `tc`, you can only add rate OR loss/delay to a VM. Enabling loss or delay will disable rate and vice versa.
- `qos` applies only to traffic received by the VM (which is "egress" traffic on the `mega_tap` interface on the host). Traffic sent by the VM ("ingress" on the `mega_tap` interface on the host) is not policed to the desired rate.
- The maximum loss allowed is 99.9. 100.0 is not possible with minimega. Instead, to replicate this behavior, you could disable the interface on the router the VM is connected to.

## Metadata Options

```yaml
metadata:
  vms:
    - hostname: <string> # (REQUIRED) Hostname of VM from topology to apply the qos limit(s) to
      interface: <integer or string>  # (Optional) Name or index of interface in VM to apply the qos limit(s) to. Default: 0 (the first non-management interface)
      loss: <float>  # Percentage of packets that should be dropped, as a floating-point number. Valid values: 0.0 - 99.9. Not able to be used if 'rate' is configured.
      delay: <string>  # How long packets should be delayed, as a time interval string. Example: "100ms" for 100 milliseconds. Not able to be used if 'rate' is configured.
      rate: <string>  # Bandwidth amount the interface should be limited to, e.g. "500 kbit" for 500 kilobits per second (kbps). Allowed units for rate: "kbit", "mbit", "gbit". Not able to be used if 'loss' or 'delay' are configured.
      variable_loss: <float>  # (Optional) Vary loss value by loop count. This value will be multiplied by the loop count to calculate the loss to apply. The any value set in the 'loss' field will be ignored.
```

## Example Configuration

```yaml
components:
  - name: qos-example
    type: qos
    metadata:
      vms:
      - hostname: rtu-2
        interface: 0  # explicitly specifying interface 0 (first interface on the host)
        loss: 25.0  # 25% of all incoming packets will be dropped
      - hostname: rtu-2  # defaults to interface 0
        delay: 1s  # every incoming packet will be delayed by 1 second
      - hostname: scada
        interface: 1  # second interface on the host
        delay: 100ms  # every incoming packet will be delayed by 100 milliseconds
      - hostname: relay-6
        rate: 500 kbit  # incoming bandwidth of interface will be limited to 500 kilobits per second (kbps)
      - hostname: relay-10
        interface: eth0
        loss: 0.0
        variable_loss: 10.0  # count 0 = 0% loss, count 1 = 10% loss, count 9 = 90% loss
```
