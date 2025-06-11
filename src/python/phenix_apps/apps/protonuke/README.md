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
