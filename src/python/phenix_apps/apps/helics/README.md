# HELICS App

This phēnix app, named `helics`, aids in the generation of HELICS broker start
scripts and injects them into the appropriate nodes in an experiment. It does
this by looking for experiment topology nodes with a `helics/federate`
annotation and parsing the annotation values to determine how many sub brokers
(if any) are needed and how many federates will be connected each broker.

This app assumes that any nodes acting as a HELICS federate will have the
`helics/federate` annotation. The `ot-sim` app automatically adds this
annotation to nodes running an `ot-sim` device that includes the `i/o` module.
The annotation can also be manually added to topology nodes. Because other apps
in an experiment scenario may annotate nodes with the `helics/federate`
annotation, users should always make sure this app is configured to run after
all other apps that may add the annotation run.

> NOTE: this app processes all nodes with the `helics/federate` annotation
> during the `pre-start` stage of an experiment.

The schema for the annotation value is described below.

```
annotations:
  helics/federate:
    - broker: 172.16.0.25:24000
      fed-count: 1
```

The schema for the `helics/federate` annotation is an array of maps, each map
specifying a broker that a federate running in the annotated node will be
connecting to, as well as how many federates will be connecting to it.

Each `helics/federate` annotation is processed according to the following. The
refereced `root broker` is specified in this app's metadata (see below).

1. If federate broker matches root broker exactly, it will connect directly to
   root broker.

2. If federate broker does not match root broker exactly, but includes a port
   number, create a sub broker that will connect to the root broker.

3. If federate broker does not match root broker exactly, and does not include a
   port number, create sub broker that will connect to root broker and assume
   port 24000 for sub broker.

4. Each unique broker `ip:port` identified in the annotations that does not
   match the root broker warrants its own sub broker.

Below is an example of all the options available in the `helics` app, with
documentation for each.

> NOTE: The `broker.root` metadata must be provided by the user, and the
> topology node referenced by `broker.root` must already exist in the topology.

```
spec:
  scenario:
    apps:
    - name: helics
      metadata:
        broker:
          root: helics-broker|IF0 # Endpoint details for root broker.
                                  # This can either be in the form of
                                  # 'hostname|iface' or an IP address with
                                  # no port. If a port is provided it will
                                  # be silently ignored, as the default
                                  # HELICS broker port is always used for
                                  # the root broker.
          log-level: summary # This is the default.
                             # Used for all generated broker start scripts.
          log-dir: /var/log  # This is the default.
                             # Used for all generated broker start scripts.
                             # Root broker will log to helics-root-broker.log
                             # in this directory. Sub brokers will log to
                             # helics-sub-broker.log in this directory.
