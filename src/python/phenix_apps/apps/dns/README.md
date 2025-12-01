
If there is already a DNS field set, the configured server will be appended to the end.


!! TODO: add DNS to list of apps in phenix docs

```yaml
apiVersion: phenix.sandia.gov/v2
kind: Scenario
metadata:
  name: dns-example
  annotations:
    topology: dns-example
spec:
  apps:
  - name: dns
    metadata:

```

```yaml
apiVersion: phenix.sandia.gov/v1
kind: Topology
metadata:
  name: dns-example-topo
spec:
  nodes:
  - type: VirtualMachine
    labels:
      dns-server: eth0
    general:
      description: "DNS server"
      hostname: dns
    hardware:
      drives:
        - image: bennu.qc2
      os_type: linux
    network:
      interfaces:
      - name: eth0
        vlan: main
        address: 192.168.0.10
        mask: 24
        gateway: 192.168.0.1
        proto: static
        type: ethernet
      - name: mgmt
        vlan: MGMT
        address: 172.16.1.10
        gateway: 172.16.1.1
        mask: 16
        proto: static
        type: ethernet
```
