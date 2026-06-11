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
```
