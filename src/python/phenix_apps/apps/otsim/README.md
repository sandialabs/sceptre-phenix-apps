# OT-sim App

This app, named `ot-sim` aids in the generation of config files for
[OT-sim](https://ot-sim.patsec.dev). It currently supports generating
configuration files for three different types of devices: a field device
(`fd-server`), a front-end processor (`fep`), and a client (`fd-client`). It
also supports generating a start script for a HELICS broker if needed.

Below is an example of all the options available in the app, with documentation
for each.

```
spec:
  scenario:
    apps:
    - name: ot-sim
      metadata:
        infrastructure: power-distribution # this is the default
        helics:
          # The broker setting has the following options:
          #   * address
          #   * hostname
          #   * base-fed-count
          # If both `hostname` and `address` are provided, `hostname`
          # takes precedence and the address for the broker will be pulled
          # from the topology. If `hostname` is provided it should include
          # the name of an interface in the topology to pull an IP from.
          # Otherwise, the first interface from the topology will be used.
          # If both `hostname` and `base-fed-count` are provided, an
          # inject will be generated and added to the topology for the
          # host to start the broker with the given number of federates
          # plus however many devices with I/O modules are configured. The
          # optional `log-level` and `log-file` options for the broker are
          # only used if a broker inject is created.
          broker:
            hostname: helics-broker|IF0
            base-fed-count: 2
            log-level: SUMMARY                   # this is the default
            log-file: /var/log/helics-broker.log # this is the default
          federate: OpenDSS # default federate to subscribe to; this is the default
        message-bus:
          pull-endpoint: tcp://127.0.0.1:1234 # this is the default
          pub-endpoint: tcp://127.0.0.1:5678  # this is the default
        cpu-module:
          api-endpoint: 0.0.0.0:9101 # this is the default; can be set to null to disable globally
                                     # can also be set per device via host metadata
        infrastructures:
          power-distribution:
            node:
              voltage:
                type: analog-read
                modbus:      # Device type variables support per-protocol configurations. Right now,
                  scaling: 2 # the Modbus protocol only looks for a single config: `scaling`. If not
                             # provided, the scaling defaults to 0. The DNP3 protocol looks for four
                             # configs: `svar`, `evar`, `class`, and `sbo`.
            bus:
              voltage:
                type: analog-read
                modbus:
                  scaling: 2
            breaker:
              voltage: analog-read # will assume Modbus scaling of 0 if not specified
              current: analog-read
              freq: analog-read
              power: analog-read
              status: binary-read
              control: binary-read-write
            capacitor:
              voltage: analog-read
              current: analog-read
              freq: analog-read
              power: analog-read
              setpt: analog-read-write
              on_off_status: binary-read
            regulator:
              voltage: analog-read
              current: analog-read
              freq: analog-read
              power: analog-read
              setpt: analog-read-write
              on_off_status: binary-read
            load:
              voltage: analog-read
              current: analog-read
              active_power: analog-read
              reactive_power: analog-read
            line:
              from_voltage: analog-read
              from_current: analog-read
              from_active_power: analog-read
              from_reactive_power: analog-read
              to_voltage: analog-read
              to_current: analog-read
              to_active_power: analog-read
              to_reactive_power: analog-read
            transformer:
              from_voltage: analog-read
              from_current: analog-read
              from_active_power: analog-read
              from_reactive_power: analog-read
              to_voltage: analog-read
              to_current: analog-read
              to_active_power: analog-read
              to_reactive_power: analog-read
      hosts:
      - hostname: outstation
        metadata:
          type: fd-server
          infrastructure: power-distribution # will default to infrastructure in app metadata if not provided

          # The `message-bus`, `helics`, and `cpu-module` keys available
          # in the app metadata can be overridden on a per host basis here.
          # The only difference is for the `helics.federate` setting,
          # which when defined in the host metadata specifies the name to
          # use for the federate the device will be providing.

          helics:
            # Defaults to helics.broker in app metadata if not provided.
            # If provided for a host, and both `hostname` and
            # `base-fed-count` are provided, a separate inject is tracked
            # and generated for the given host in the topology file. Similar
            # to the app metadata, `log-level` and `log-file` can also be
            # specified.
            broker:
              address: helics-broker.other.network.test
            federate:
              name: outstation-fed # name to use for this federate; defaults to hostname if not provided
              log-level: SUMMARY   # log level to pass to I/O module's init string; this is the default

          # The `modbus` and `dnp3` sections can take two forms. The first
          # is an array of device name/type configs, in which case the app
          # will assume the host running the device should listen on the
          # first interface defined in the topology file for the protocol.
          # The second is a map containing the `interface` key and the
          # `devices` key. In this form, the `devices` value will be an
          # array of name/type configs like before and the `interface` value
          # will specify the interface the device should listen on for the
          # protocol. The interface can be specified as an actual IP:port
          # to listen on or it can be an interface name:port to listen on,
          # in which case the IP is pulled from the topology file. For
          # either, if no port is specified, the default port for the
          # protocol will be used.

          modbus:
          # Will default to listening on port 502 of the IP configured for
          # the first interface defined in the topology file.
          - name: OpenDSS/bus-01 # name of topic key from another federate to subscribe to
                                 # defaults to helics.federate in app metadata if 'OpenDSS/' (federate name) is left off
            type: bus            # type of device for topic key -- this determines values to publish and subscribe to based on infrastructure
          dnp3:
            interface: IF1:20000
            devices:
            - name: line-01-03
              type: branch
```
