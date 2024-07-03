# Caldera App

This app, named `caldera`, aids in the creation of one or more nodes in the
topology running an instance of [MITRE Caldera](https://caldera.mitre.org). It
also supports automatically injecting Caldera Sandcat agents into existing
Windows and Linux hosts in the topology.

Below is an example of all the options available in the app, with documentation
for each.

```
spec:
  scenario:
    apps:
    - name: caldera
      metadata:
        servers: # list of Caldera servers to add to the topology
        - hostname: mallory  # defaults to 'caldera-<idx>' (in this case, caldera-0)
          image: caldera.qc2 # this is the default
          cpu: 2             # this is the default
          memory: 8192       # this is the default
          interfaces: # interface names default to 'IF<idx>' (in this case, IF0)
          - vlan: WWW
            address: 1.2.3.4/16
            gateway: 1.2.255.254
          facts:
          - /path/to/facts.yml
          adversaries:
          - /path/to/adversary.yml
          config: /path/to/config.yml # will default to default config template
      hosts: # list of existing topology hosts to inject the Caldera agent into
      - hostname: alice
        metadata:
          server: mallory:0 # will default to interface 0 if ':<idx>' isn't provided
                            # can also be an IP address (for external server)
```