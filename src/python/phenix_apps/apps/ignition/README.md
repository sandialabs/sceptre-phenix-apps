# Ignition App

**Language:** Python

## Overview

Configures an Inductive Automation Ignition Gateway 8.3 SCADA master at experiment start.
The app renders one DNP3 device connection per RTU and names the RTU's points after
the infrastructure devices behind them, read from the `ot-sim` app in the same scenario
(see [Point mapping from ot-sim](#point-mapping-from-ot-sim)). RTUs that ot-sim does not
define are discovered instead.
* With `perspective`, the app additionally generates a basic Perspective table for
viewing data and sending commands.
* With `api`, a WebDev resource exposes the tags over HTTP: `GET` to read, and `POST` to
issue analog-output setpoint or binary CROB commands.
* With `historian`, Ignition's native SQL Historian records OPC tag changes to an
existing PostgreSQL database using passwordless authentication.

Alternatively, if `gwbk` points at a hand-authored gateway backup, the app injects it
untouched and restores it at boot via `gwcmd.bat -s <file> -m`.

## Spec / Configuration

```yaml
spec:
  scenario:
    apps:
      - name: ignition
        hosts:
          - hostname: OT-scada
            metadata:
              type: gateway
              polling:              # optional DNP3 poll periods (ms) for every RTU
                class1: 1000
              connected_rtus:
                - rtu-1             # plain hostname, defaults below
                - hostname: rtu-2   # or per-RTU overrides
                  name: custom-name
                  port: 20000
                  source_address: 1
                  destination_address: 1024
                  interface: eth0
                  points: auto      # auto | otsim | discover
                  polling:          # overrides the gateway's periods per field
                    class2: 2000
                    integrity: 60000
              perspective: true     # optional HMI; or an options object:
              # perspective:
              #   project: hmi
              #   open_client: true
              api: true             # unauthenticated API
              # For authenticated control over HTTPS:
              # api:
              #   auth: true
              #   require_https: true
              #   roles: [Administrator]
              historian:            # optional; requires passwordless PostgreSQL access
                ip: 192.0.2.20
                port: 5432          # optional
                user: ignition
                database: ignition
              # OR (mutually exclusive with connected_rtus, perspective, api, and historian)
              # restore a hand-authored backup verbatim:
              # gwbk: /phenix/injects/${BRANCH_NAME}/ignition/base.gwbk
          - hostname: hmi-1
            metadata:
              type: perspective     # dedicated HMI desktop (optional)
              # connected_gateway: OT-scada   # only needed with >1 HMI gateway
```

### `type: gateway`

| Option           | Default   | Description                                                                  |
|------------------|-----------|------------------------------------------------------------------------------|
| `type`           | `gateway` | Host role; `gateway` or `perspective`                             |      
| `connected_rtus` | `[]`      | RTUs to connect to; plain hostname strings or override objects (below).      |
| `polling`        | (below)   | DNP3 poll periods for every `connected_rtus` device (below). Requires `connected_rtus`. |
| `perspective`    | (none)    | Generate a basic Perspective HMI; `true` for defaults or an options object (below). Requires `connected_rtus`. |
| `api`            | (none)    | Serve a WebDev tag API; `true` for defaults or an options object (below). Independent of `perspective` and `connected_rtus`. |
| `historian`      | (none)    | Native PostgreSQL tag history; independent of Perspective/API and able to discover devices already on the gateway. |
| `gwbk`           | (none)    | Path on the phenix host to a complete `.gwbk` to restore verbatim. Mutually exclusive with `connected_rtus`, `perspective`, `api`, and `historian`. |

#### `connected_rtus` entries

| Option                | Default          | Description                                          |
|-----------------------|------------------|------------------------------------------------------|
| `hostname`            | (required)       | Topology hostname of the outstation.                 |
| `name`                | hostname         | Ignition device name; tags reference it (e.g. `[custom-name]AnalogInput0`). Letters, digits, spaces, `_` and `-`, starting with a letter or digit, 2 to 63 characters, not `all` or `phenix`. |
| `port`                | ot-sim listen port, else `20000` | Outstation TCP port.                   |
| `source_address`      | `1`              | DNP3 master address (ot-sim default).                        |
| `destination_address` | `1024`           | DNP3 outstation address (ot-sim default).            |
| `interface`           | ot-sim listen interface, else first interface | Which topology interface's address to connect to. |
| `points`              | `auto`           | `auto`: name points from ot-sim when the RTU is an ot-sim outstation, else discover them. Other options are `otsim` (require the ot-sim definition), or `discover` (always discover, ignoring ot-sim). |
| `polling`             | gateway `polling` | Poll periods for this specific RTU; each field set here overrides the gateway's. |

##### `points:`

**`ot-sim` (or `auto` with an ot-sim outstation)**

The ignition app re-uses ot-sim's deterministic numbering to name each point at build time.
In the ot-sim app: each `fd-server` lists infrastructure devices (`name: cap1, type: capacitor`),
the infrastructure mapping lists variables (`voltage`, `setpt`, ...); a `fep` serves every register
of its `upstream` IEDs.

**`discover` (or `auto` with no ot-sim outstation)**

RTUs without an ot-sim definition are populated on the gateway rather than at build
time. The app seeds the provider with a `_TagSync_` expression tag whose `valueChanged`
event script runs every 30 seconds. For any `discover` device it browses the OPC server and
mirrors every point it finds into the provider with a merge, under the DNP3 point names
(`AnalogInput0`, `BinaryOutput3`, ...).

#### `polling:` options

Periods are in milliseconds, 0 through 2147483647; `0` disables that poll. Class polls
only return points the outstation assigns to that event class.

| Option      | Default  | Description                          |
|-------------|----------|--------------------------------------|
| `class1`    | `5000`   | Class 1 event poll period.           |
| `class2`    | `5000`   | Class 2 event poll period.           |
| `class3`    | `5000`   | Class 3 event poll period.           |
| `integrity` | `300000` | Integrity (Class 1/2/3/0) poll period. |

#### `perspective:` options

| Option        | Default | Description                                                            |
|---------------|---------|------------------------------------------------------------------------|
| `project`     | `hmi`   | Ignition project name; the HMI is served at `http://<gateway>:8088/data/perspective/client/<project>`. |
| `open_client` | `true`  | Also auto-open the HMI in Firefox on the gateway's own console at boot. |

#### `api:` options

| Option        | Default   | Description                                                                          |
|---------------|-----------|--------------------------------------------------------------------------------------|
| `auth`        | `false`   | Require HTTP Basic auth on the `POST` (control) endpoint; reads stay open.            |
| `require_https` | `false` | Require HTTPS on the `POST` endpoint. Configure TLS on the gateway before enabling. |
| `roles`       | `[]`      | When `auth` is set, restrict control to users holding at least one of these roles.   |
| `user_source` | `default` | Gateway User Source profile that `auth` validates credentials against.               |

#### `historian:` options

| Option   | Default | Description                                                                 |
|----------|---------|-----------------------------------------------------------------------------|
| `ip`     | (none)  | PostgreSQL host IP address; required.                                        |
| `port`   | `5432`  | PostgreSQL TCP port.                                                         |
| `user`   | (none)  | PostgreSQL user; required.                                                   |
| `database` | (none) | PostgreSQL database name; required.                                        |

### `type: perspective`

| Option              | Default         | Description                                            |
|---------------------|-----------------|--------------------------------------------------------|
| `connected_gateway` | (auto)          | Gateway hostname to point at; only required when more than one gateway has `perspective` enabled. |
| `interface`         | first interface | Which *gateway* interface's address to use in the URL. |

## HMI

### Perspective dashboards

A basic Perspective HMI is generated with:
* an overview tab (per-RTU connection status table)
* one dashboard tab per RTU showing every tag's value and description
* a simple popup for sending commands. The `DNP3 Command` button above each table, or
double-clicking a row, opens the DNP3 command popup to send one of:
  * DNP3 CROB commands
  * analog output setpoints (Group 41 variation 1 Int32, 2 Int16, 3 Float32, or
    4 Float64)
  * on-demand class/integrity data polls

### Browser auto-open

With `open_client` (and on every `type: perspective` host) a startup script at
`/phenix/startup/99-ignition-perspective.ps1` opens the HMI URL in Firefox at boot.

## Historian

`historian` requires `ip`, `user`, and an existing `database`; `port` defaults to 5432.
PostgreSQL only. Passwordless access is required. Database provisioning is outside this
app's scope.

The native connection/provider is named `phenix-history`. OPC history uses on-change
sampling, discrete zero deadband, no minimum interval, and no forced periodic samples.
It records changes observed by Ignition, not every physical transition between polls.
Either historian or Perspective enables one shared discovery seed. Existing OPC tags
receive history-only merges; unrelated settings are preserved and failed updates are
reported and retried. Folders, memory/expression tags, and `_TagSync_` are excluded.

## REST API

With `api`, a `tags` WebDev resource is served at
`http://<gateway>:8088/system/webdev/api/tags`.

### Read points

**`GET`** reads every device's tags, keyed by device then tag path below the device
folder. Optional `?device=<name>` limits the response to one device.

```json
{
  "rtu-1": {
    "cap1/voltage": 120.0,
    "cap1/setpt": 1.0
  }
}
```

```bash
# every point on every device
curl http://<gateway>:8088/system/webdev/api/tags

# just one device
curl 'http://<gateway>:8088/system/webdev/api/tags?device=rtu-1'

# include OPC quality and source timestamp (Unix epoch milliseconds)
curl 'http://<gateway>:8088/system/webdev/api/tags?device=rtu-1&details=true'
```

With `details=true`, each point's value becomes an object that also carries its OPC
address:

```json
{
  "rtu-1": {
    "cap1/voltage": {
      "value": 120.0,
      "quality": "Good",
      "timestamp": 1788883200000,
      "address": "ns=1;s=[rtu-1]AnalogInput4"
    }
  }
}
```

### Command addressing

**`POST`** accepts a JSON object with an explicit target, either a tag path or a DNP3
address:

| Field | Required | Description |
|-------|----------|-------------|
| `tag` | Either | Tag path below `[default]`, such as `rtu-1/cap1/setpt` or `rtu-1/671692/controls`. The device, point type and index are read from the tag's OPC address; a tag that is not an output point is rejected. Cannot be combined with the fields below. |
| `deviceName` | Either | Exact Ignition device name, such as `rtu-1` or a `connected_rtus` name override. |
| `pointType` | Either | `analog` or `binary`; there is no default. |
| `index` | Either | Integer output index, 0 through 65535, within that point type on the device. |

### Analog outputs

Use `pointType: "analog"` for numeric setpoints, including OT-sim capacitor and
regulator `.setpt` outputs.

| Field | Default | Description |
|-------|---------|-------------|
| `value` | Required | Finite JSON number in the selected encoding's range. Booleans and strings are rejected. |
| `variation` | `3` | Group 41 encoding: 1 = signed 32-bit integer, 2 = signed 16-bit integer, 3 = 32-bit float, 4 = 64-bit float. |

```bash
curl -u operator -X POST https://<gateway>:8043/system/webdev/api/tags \
     -H 'Content-Type: application/json' \
     -d '{"tag": "rtu-1/cap1/setpt", "value": 1.05}'

# the same setpoint by DNP3 address
curl -u operator -X POST https://<gateway>:8043/system/webdev/api/tags \
     -H 'Content-Type: application/json' \
     -d '{"deviceName": "rtu-1", "pointType": "analog", "index": 1, "variation": 3, "value": 1.05}'
```

### Binary outputs

Use `pointType: "binary"` for breaker/switch CROB commands.

| Field        | Default | Description                                        |
|--------------|---------|----------------------------------------------------|
| `tcc`        | `1`     | Trip/close code: 0 NUL, 1 CLOSE, 2 TRIP.           |
| `opType`     | `3`     | 0 NUL, 1 PULSE_ON, 2 PULSE_OFF, 3 LATCH_ON, 4 LATCH_OFF. |
| `count`      | `1`     | Operation count, 1 through 255.                     |
| `onTime`     | `1000`  | On time, 0 through 2147483647 ms.                    |
| `offTime`    | `1000`  | Off time, 0 through 2147483647 ms.                   |

```bash
curl -u operator -X POST https://<gateway>:8043/system/webdev/api/tags \
     -H 'Content-Type: application/json' \
     -d '{"tag": "rtu-1/671692/controls", "tcc": 0, "opType": 3}'
```

CROB meanings depend on the outstation's implementation. Choose trip/close and
latch/pulse parameters for that device rather than assuming the API defaults
match every breaker.

### Authentication

> [!WARNING]
> The `api.auth` settings are untested and may require additional configuration on the gateway.

For authenticated control, use:

```yaml
api:
  auth: true
  require_https: true
  roles: [Operator]
  user_source: default
```

Configure the gateway's TLS listener and an appropriate user/role in that User Source.
`auth` requires HTTP Basic credentials for POST; reads remain open. `require_https`
uses WebDev's HTTPS requirement on POST and requires gateway TLS configuration.

## Testing

Unit tests live in `tests/`:

```bash
pytest phenix_apps/apps/ignition/tests
```

`tests/test_ignition_input.yaml` is a sample experiment for manual dry-runs against the
full app entry point, without a live phenix system:

```bash
PHENIX_LOG_FILE="" phenix-app-ignition pre-start --dry-run < phenix_apps/apps/ignition/tests/test_ignition_input.yaml
```

## Dependencies

### Apps

* Semantic point names need the `ot-sim` app in the same scenario, with the RTUs defined
  as `fep` or `fd-server` hosts. The mapping is computed from ot-sim's own classes
  (`phenix_apps.apps.otsim.points`), so the two apps must come from the same package.

### Images

* Only developed and tested with Igntion 8.3.1.
* Only works for Windows hosts.
* Only works for DNP3 outstations.
* `api` requires the WebDev module installed and enabled on the gateway.
* `historian` requires Historian Core, SQL Historian, and PostgreSQL JDBC installed
  and licensed or in an active trial.
* Expects VMs configured to run all scripts in `C:\phenix\startup` and `C:\phenix\user-startup` at boot.
* Expects `firefox.exe` in the path.
* Expects the ignition service to start automatically at boot.
