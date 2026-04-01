# ERSPAN Component

Scorch component to set up network traffic mirroring from a phenix experiment (openvswitch bridge) to a remote capture host via ERSPAN.
Optionally, it can connect to the remote host and autoconfigure the receiver.

When using the remote_config functionality, the remote user must be able to run `sudo ip link`, `sudo ovs-vsctl`, and `sudo ovs-ofctl` commands without a password prompt.

```
type:   erspan
exe:    phenix-scorch-component-erspan
stages: configure, cleanup
```

## Metadata Options

```yaml
metadata:
  local_bridge: <string>    # (REQUIRED) Phenix experiment bridge name.
  local_ip: <string>        # (REQUIRED) IP address of management interface on phenix server.
  remote_ip: <string>       # (REQUIRED) IP address of Collection Server openvswitch bridge.
  local_interface: <string> # (OPTIONAL) Name of the local erspan interface to create. Default: erspan1
  session_key: <integer>    # (OPTIONAL) Session key for the erspan connection. Default: 100
  excluded_vlans: <list of strings> # (OPTIONAL) A list of VLAN names to exclude from the mirror. If not provided, no VLANs are excluded.
  remote_config:            # (OPTIONAL) If provided, the component will also configure the remote receiver via SSH. If omitted, only the local erspan interface and mirror are configured.
    remote_bridge: <string>    # (OPTIONAL) Collection Server openvswitch bridge name. If omitted, ovs-vsctl and ovs-ofctl (packet flooding) configuration portions are skipped on the remote receiver. The bridge must already exist on the remote receiver.
    remote_interface: <string> # (OPTIONAL) Name of the erspan interface to create on the remote host. Default: erspan1
    ssh_ip: <string>           # (REQUIRED) Login IP of the Remote Collection Server.
    user: <string>             # (REQUIRED) User name of the Remote Collection Server.
    password: <string>         # (OPTIONAL) Password of the Remote Collection Server. If not provided, the connection will be attempted without a password, meaning an SSH key will need to be already established with the remote server and available at the default location ($HOME/.ssh). If running phenix in a container, the SSH key will need to be in /root/.ssh in the container.
```

## Example Configurations

### Local-Only (no remote receiver setup)

Use this when you are configuring the remote receiver yourself, or it is already configured. The component will only set up the local ERSPAN interface and OVS mirror.

```yaml
components:
  - name: erspan-local-only
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      excluded_vlans:
        - mgmt
```

### Full (local + remote receiver with OVS bridge)

Use this when you want the component to set up both the local ERSPAN interface/mirror and configure the remote receiver via SSH, including attaching it to an OVS bridge on the remote side and flooding traffic to all ports on that bridge. This can be useful when you have multiple VMs on the remote side that you want to receive the same mirrored traffic.

```yaml
components:
  - name: erspan-full
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      local_interface: erspan1
      session_key: 100
      excluded_vlans:
        - mgmt
      remote_config:
        remote_bridge: vmbr0
        remote_interface: erspan1
        ssh_ip: 192.168.1.3
        user: ubuntu
        password: ubuntu
```

### Remote interface only (no OVS bridge on remote receiver)

Use this when you want the component to set up the ERSPAN link on the remote receiver, but you do not want it attached to an Open vSwitch bridge.

```yaml
components:
  - name: erspan-interface-only
    type: erspan
    metadata:
      local_bridge: phenix
      local_ip: 192.168.1.2
      remote_ip: 192.168.1.3
      remote_config:
        ssh_ip: 192.168.1.3
        user: ubuntu
```
