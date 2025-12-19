> **DEPRECATED**: This standalone `wind-turbine` application is deprecated and will be removed in a future release. Its functionality has been migrated to the `wind_turbine` plugin within the new `scale` application, which offers superior scalability and configuration management. Please see the `app_migration_guide.md` documentation for details on how to migrate.
>
> ---

# Wind Turbine phenix App

## Wildcard Method

```yaml
spec:
  apps:
  - name: wind-turbine
    metadata:
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
        endpoint: updates # default endpoint to send updates to on default federate
                          # this is the default; set it to false to disable using
                          # endpoints for updates
      ground-truth-module:
        elastic:
          endpoint: http://localhost:9200 # endpoint for ElasticSearch cluster
          index-base-name: ot-sim         # base name for index ground truth data is written to;
                                          # will be appended with current date stamp in the form
                                          # of "-YYYY.mm.dd"
      templates:
        default:
          main-controller:
            turbine:
              type: E-126/4200
              hubHeight: 135
              roughnessLength: 0.15
              helicsTopic: generator-$2_bus-2100.mw_setpoint
              dnp3SBO: false
            logic:
              speedTag: speed.high
              directionTag: dir.high
              directionError: 0.04
            node-red:
              flow: /phenix/injects/foobar/node-red-flow.json
              endpoint:
                host: 0.0.0.0
                port: 1880
              auth:
                editor:
                  user: admin
                  pass: admin
                ui:
                  user: foo
                  pass: bar
            weather:
              columns:
              - name: wind_speed
                tags:
                - name: speed.high
                  height: 58.2
                - name: speed.med
                  height: 36.6
                - name: speed.low
                  height: 15.0
              - name: temperature
                tags:
                - name: temp.high
                  height: 58.2
                - name: temp.low
                  height: 3.0
              - name: pressure
                tags:
                - name: pressure
                  height: 0.0
          anemometer:
            weather:
              replayData: /phenix/injects/{{BRANCH_NAME}}/weather.csv
              columns:
              - name: Windspeed 58.2m
                tag: speed.high
              - name: Windspeed 36.6m
                tag: speed.med
              - name: Windspeed 15.0m
                tag: speed.low
              - name: Wind Direction 58.2m
                tag: dir.high
              - name: Wind Direction 36.6m
                tag: dir.med
              - name: Wind Direction 15.0m
                tag: dir.low
              - name: Temperature 58.2m
                tag: temp.high
              - name: Temperature 3.0m
                tag: temp.low
              - name: Barometric Pressure
                tag: pressure
          yaw-controller:
            yaw:
              initialPosition: 0
              degreePerSecond: 0.1
    hosts:
    - hostname: (.*-(.*))-main_controller
      metadata:
        type: main-controller
        template: default
        controllers:
          anemometer: $1-signal_converter
          yaw: $1-yaw_controller
          blades:
          - $1-blade_1
          - $1-blade_2
          - $1-blade_3
        ground-truth-module:
          elastic:
            labels:
              turbine: $1
```

## Verbose Method

```yaml
spec:
  apps:
  - name: wind-turbine
    hosts:
    - hostname: wtg-01-main_controller
      metadata:
        type: main-controller
        turbine:
          type: E-126/4200
          hubHeight: 135
          roughnessLength: 0.15
        logic:
          speedTag: speed.high
          directionTag: dir.high
          directionError: 0.04
        weather:
          columns:
          - name: wind_speed
            tags:
            - name: speed.high
              height: 58.2
            - name: speed.med
              height: 36.6
            - name: speed.low
              height: 15.0
          - name: temperature
            tags:
            - name: temp.high
              height: 58.2
            - name: temp.low
              height: 3.0
          - name: pressure
            tags:
            - name: pressure
              height: 0.0
        controllers:
          anemometer: wtg-01-signal_converter
          yaw: wtg-01-yaw_controller
          blades:
          - wtg-01-blade_1
          - wtg-01-blade_2
          - wtg-01-blade_3
    - hostname: wtg-01-signal_converter
      metadata:
        type: anemometer
        weather:
          replayData: /phenix/injects/{{BRANCH_NAME}}/weather.csv
          columns:
          - name: Windspeed 58.2m
            tag: speed.high
          - name: Windspeed 36.6m
            tag: speed.med
          - name: Windspeed 15.0m
            tag: speed.low
          - name: Wind Direction 58.2m
            tag: dir.high
          - name: Wind Direction 36.6m
            tag: dir.med
          - name: Wind Direction 15.0m
            tag: dir.low
          - name: Temperature 58.2m
            tag: temp.high
          - name: Temperature 3.0m
            tag: temp.low
          - name: Barometric Pressure
            tag: pressure
    - hostname: wtg-01-yaw_controller
      metadata:
        type: yaw-controller
        yaw:
          initialPosition: 0
          degreePerSecond: 0.1
```
