# Management tap user application

This user application will create a tap on the management network of the
experiment it is assigned to, allowing a user to copy files to and from
machines in the network as long as the vm has a connection to the
management network.

E.g.
```yaml
- name: mgmt_tap
  metadata:
    subnet: 172.16.0.0/16
    vlan: MGMT_1
    bridge: phenix
```

## Metadata

| Key      | Required | Default                                   | Description                                        |
| -------- | -------- | ----------------------------------------- | -------------------------------------------------- |
| `subnet` | no       | `172.16.0.0/16`                           | Subnet used to address the host taps.               |
| `vlan`   | no       | `MGMT`                                    | VLAN alias the tap is attached to.                  |
| `bridge` | no       | experiment `spec.defaultBridge` (`phenix`) | OVS bridge the host tap is created on.              |

If `bridge` is not set, the app uses the experiment's `spec.defaultBridge`.
If the experiment does not define one, it falls back to `phenix`.
