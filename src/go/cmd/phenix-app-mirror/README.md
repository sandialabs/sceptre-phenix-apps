### mirror

The `mirror` app configures cluster-wide packet mirroring for specific VLANs
to a specific interface on a predefined node using GRE tunnels.

For example, let's assume the app is configured as follows in the scenario
file:

```yaml
apiVersion: phenix.sandia.gov/v2
kind: Scenario
metadata:
  name: foobar
  annotations:
    topology: traffic-gen
spec:
  apps:
  - name: mirror
    hosts:
    - hostname: monitor
      metadata:
        interface: IF0
        vlans:
        - EXP_1
```

Given the above configuration, each cluster host participating in the
experiment except for the cluster host the `monitor` VM is scheduled on will
create a GRE tunnel port in OVS to the cluster host the `monitor` VM is
scheduled on. Each cluster host will also create an OVS mirror that includes
taps from all VMs with an interface in the `EXP_1` VLAN that are not routers
or firewalls, using the GRE tunnel as the destination port for the mirrored
traffic, except for the cluster host the `monitor` VM is scheduled on, which
will instead use the tap of the `IF0` interface for the `monitor` VM as the
mirror destination.

#### Mirror limit

Open vSwitch applies at most 32 mirrors on one bridge, and it ignores a 33rd
mirror without an error. Before each cluster host creates its mirror, the app
counts the mirrors on the bridge. If the bridge already has 32, the stage fails
with `no Open vSwitch mirror left: bridge <bridge> on cluster host <host> has
32 of 32 Open vSwitch mirrors`. Packet captures of minimega and other mirrors
use the same limit. Remove a mirror, or use another bridge.

Each mirror has the Open vSwitch tags `external_ids:minimega-namespace` (the
experiment name) and `external_ids:minimega-kind=app-mirror`. phēnix uses them
to count the mirror for the experiment.
