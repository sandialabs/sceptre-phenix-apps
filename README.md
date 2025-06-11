# phenix-apps

Apps written to work with the latest version of
[phenix](https://github.com/sandialabs/sceptre-phenix).

* Accept stage as single argument.
* Accept experiment JSON over STDIN.
* Return updated experiment JSON over STDOUT.
* Write JSON logs to the file specified by the `PHENIX_LOG_FILE` environment variable.

## Apps

Below are relevant notes for each phenix app available in this repo.

### ot-sim

The `ot-sim` app aids in the generation of configuration files for
[OT-sim](https://ot-sim.patsec.dev). The configuration options it provides can
be found [here](src/python/phenix_apps/apps/otsim/README.md).

### protonuke

The `protonuke` app simply injects the `/etc/default/protonuke` file into
each app host that sets the `PROTONUKE_ARGS` environment variable used by the
`protonuke` systemd service to whatever the `args` metadata key is set to.
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
  - name: protonuke
    hosts:
    - hostname: client
      metadata:
        args: -http 192.168.1.254
    - hostname: server
      metadata:
        args: -serve -http
```

The result of this would be for the following files to be injected into the
`client` and `server` nodes:

```shell
# injected into client node at /etc/default/protonuke
PROTONUKE_ARGS=-http 192.168.1.254
```

```shell
# injected into server node at /etc/default/protonuke
PROTONUKE_ARGS=-serve -http
```

This assumes the `protonuke` image available as a default image config is being used.

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

> **NOTE**: the `mirror` app is currently not namespace aware, and will fail
> miserably if two different experiments use the same name for a VM that
> mirrored traffic is to be sent to. This will be addressed in a future
> version of the app.

### Additional apps

- [caldera](src/python/phenix_apps/apps/caldera)
- [helics](src/python/phenix_apps/apps/helics)
- [sceptre](src/python/phenix_apps/apps/sceptre)
- [scorch](src/python/phenix_apps/apps/scorch) - This contains Scorch components
- [wind_turbine](src/python/phenix_apps/apps/wind_turbine)
- [wireguard](src/python/phenix_apps/apps/wireguard)

## Scorch components

- [art](src/python/phenix_apps/apps/scorch/art)
- [caldera](src/python/phenix_apps/apps/scorch/caldera)
- [cc](src/python/phenix_apps/apps/scorch/cc)
- [collector](src/python/phenix_apps/apps/scorch/collector)
- [disruption](src/python/phenix_apps/apps/scorch/disruption)
- [ettercap](src/python/phenix_apps/apps/scorch/ettercap)
- [hoststats](src/python/phenix_apps/apps/scorch/hoststats)
- [iperf](src/python/phenix_apps/apps/scorch/iperf)
- [mm](src/python/phenix_apps/apps/scorch/mm)
- [opcexport](src/python/phenix_apps/apps/scorch/opcexport)
- [pcap](src/python/phenix_apps/apps/scorch/pcap)
- [qos](src/python/phenix_apps/apps/scorch/qos)
- [rtds](src/python/phenix_apps/apps/scorch/rtds)
- [snort](src/python/phenix_apps/apps/scorch/snort)
- [tcpdump](src/python/phenix_apps/apps/scorch/tcpdump)
- [trafficgen](src/python/phenix_apps/apps/scorch/trafficgen)
- [vmstats](src/python/phenix_apps/apps/scorch/vmstats)
