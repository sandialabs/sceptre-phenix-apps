# Traffic Generator

## Metadata Options

```
metadata:
  scripts:
    trafficServer: /phenix/topologies/trafficgen-test/scripts/traffic-server.py
    backgroundGen: /phenix/topologies/trafficgen-test/scripts/background-gen.py
    malwareGen: /phenix/topologies/trafficgen-test/scripts/malware-gen.py
  targets:
  - hostname: traffic-server # default value if not provided
    interface: IF0 # default value if not provided
    duration: 30
    backgroundClient:
      hostname: background-gen
      rate: 10000
      probability: .01
    malwareClient:
      hostname: malware-gen
      rate: 20
      probability: 1.25
```
