# minimega (mm) Component

```
type: mm
exe:  phenix-scorch-component-mm
```

## Metadata Options

```
metadata:
  configure:
  - type: start_capture
    capture:
      bridge: phenix
      filename: capture.pcap # will be auto generated as <bridge>-<ts>.pcap if not provided
      filter: port 80 # typical BPF filter expression
      snaplen: null
  - type: stop_capture
    capture:
      bridge: phenix
      convert: true # convert to JSON (for parsing into Elastic, for example) (default is false)
  start: [] # same array of keys as above
  stop: [] # same array of keys as above
  cleanup: [] # same array of keys as above
  vms:
  - hostname: <string>
    configure:
    - type: start # can be start, stop, connect, disconnect, start_capture, stop_capture
    - type: stop
    - type: connect # can also be used to move an already connected interface
      connect:
        interface: 0 # index of interface
        vlan: FOO
        bridge: phenix # will use the same bridge previously connected to (if moving) if not provided
    - type: disconnect
      disconnect:
        interface: 0 # index of interface
    - type: start_capture
      capture:
        interface: 0
        filename: capture.pcap # will be auto generated as <host>-<iface>-<ts>.pcap if not provided
        filter: port 80 # typical BPF filter expression
        snaplen: null
    - type: stop_capture # will stop captures on all interfaces (minimega limitation)
      capture:
        convert: true # convert to JSON (for parsing into Elastic, for example) (default is false)
    start: [] # same array of keys as above
    stop: [] # same array of keys as above
    cleanup: [] # same array of keys as above
```