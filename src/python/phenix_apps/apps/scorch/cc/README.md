# minimega Command and Control (cc) Component

```
type: cc
exe:  phenix-scorch-component-cc
```

## Metadata Options

```
metadata:
  vms:
  - hostname:
    configure:
    - type: exec # can be exec, background, send, or recv
      args: whoami # a simple string of args (not an array)
      wait: <bool> # wait for cmd to be executed by VM (default: false)
    start: [] # same array of keys as above
    stop: [] # same array of keys as above
    cleanup: [] # same array of keys as above
```

## Example Configuration

```
components:
  - name: disable-eth0
    type: cc
    metadata:
      vms:
      - hostname: foobar
        start:
        - type: exec
          args: ip link set eth0 down
          wait: true
        stop:
        - type: exec
          args: ip link set eth0 up
```
