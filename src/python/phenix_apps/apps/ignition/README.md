# Ignition App

**Language:** Python

[[_TOC_]]

## Overview

Configures an Inductive Automation Ignition Gateway 8.3 SCADA master at experiment start,
from a fresh install. The app discovers DNP3 outstation (RTU) IP addresses from the topology
and renders one Ignition device-connection resource per RTU (Ignition 8.3 stores gateway
config as plain JSON resource folders), which are injected into the VM and copied into the
gateway's `data/config` tree at boot. No extra inputs required.

With `perspective`, the app additionally generates a basic Perspective HMI: a project with
an overview page (per-RTU connection status table) and one dashboard tab per RTU showing
every tag's value, plus a popup for sending DNP3 CROB commands. Tags are imported on the
gateway itself — a generated sync tag periodically browses each device on the OPC server
and mirrors every point into the `[default]` provider — so the HMI shows whatever each
outstation actually serves, whether that is a field device, a FEP/data concentrator
aggregating several IEDs, or real hardware.

Alternatively, if `gwbk` points at a hand-authored gateway backup, the app injects it
untouched and restores it at boot via `gwcmd.bat -s <file> -m`. Use this for a pre-built
project/HMI (`gwbk` cannot be combined with `perspective`).

In both cases a generated PowerShell script at `/phenix/startup/99-ignition.ps1` applies the
config on first boot: it stops the `Ignition` service, applies the payload, and restarts the
service. The staged payload is deleted once applied, so later reboots find nothing staged and
skip straight past; a boot that fails partway leaves the payload in place and retries on the
next boot.

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
              connected_rtus:
                - rtu-1             # plain hostname, defaults below
                - hostname: rtu-2   # or per-RTU overrides
                  name: custom-name
                  port: 20000
                  source_address: 1
                  destination_address: 1024
                  interface: eth0
              perspective: true     # optional HMI; or an options object:
              # perspective:
              #   project: hmi
              #   open_client: true
              # OR (mutually exclusive with connected_rtus and perspective)
              # restore a hand-authored backup verbatim:
              # gwbk: /phenix/injects/${BRANCH_NAME}/ignition/base.gwbk
          - hostname: hmi-1
            metadata:
              type: perspective     # dedicated HMI desktop (optional)
              # connected_gateway: OT-scada   # only needed with >1 HMI gateway
```

### Host metadata (`type: gateway`)

| Option           | Default   | Description                                                                  |
|------------------|-----------|------------------------------------------------------------------------------|
| `type`           | `gateway` | Host role; `gateway` and `perspective` are implemented today.                |
| `connected_rtus` | `[]`      | RTUs to connect to; plain hostname strings or override objects (below).      |
| `perspective`    | (none)    | Generate a basic Perspective HMI; `true` for defaults or an options object (below). Requires `connected_rtus`. |
| `gwbk`           | (none)    | Path on the phenix host to a complete `.gwbk` to restore verbatim. Mutually exclusive with `connected_rtus` and `perspective`. |

### Per-RTU options (`connected_rtus` entries)

| Option                | Default          | Description                                          |
|-----------------------|------------------|------------------------------------------------------|
| `hostname`            | (required)       | Topology hostname of the outstation.                 |
| `name`                | hostname         | Ignition device name; tags reference it (e.g. `[custom-name]AnalogInput0`). |
| `port`                | `20000`          | Outstation TCP port.                                 |
| `source_address`      | `1`              | DNP3 master (source) address.                        |
| `destination_address` | `1024`           | DNP3 outstation address (ot-sim default).            |
| `interface`           | first interface  | Which topology interface's address to connect to.    |

## Perspective HMI

`perspective` options (on a `type: gateway` host):

| Option        | Default | Description                                                            |
|---------------|---------|------------------------------------------------------------------------|
| `project`     | `hmi`   | Ignition project name; the HMI is served at `http://<gateway>:8088/data/perspective/client/<project>`. |
| `open_client` | `true`  | Also auto-open the HMI in a browser on the gateway's own console at logon. |

`type: perspective` host metadata (a dedicated HMI desktop that auto-opens the page at
logon):

| Option              | Default         | Description                                            |
|---------------------|-----------------|--------------------------------------------------------|
| `connected_gateway` | (auto)          | Gateway hostname to point at; only required when more than one gateway has `perspective` enabled. |
| `interface`         | first interface | Which *gateway* interface's address to use in the URL. |

### Tag auto-import

The HMI browses the `[default]` tag provider at runtime, and the provider is populated on
the gateway rather than at build time. The app seeds it with a single `_TagSync_`
expression tag whose `valueChanged` event script runs every 30 seconds: for each
configured device it browses the OPC server and mirrors every point it finds — folder
structure, OPC item path, and data type — into the provider with a merge, so hand-added
tags survive.

The DNP3 driver learns its point map by polling the outstation, so tags appear shortly
after a device connects and keep the driver's flat point names (`AnalogInput0`,
`BinaryOutput1`, ..., plus the driver's `[Diagnostics]` folder, sanitized to
`_Diagnostics_` since brackets are illegal in tag names); the browse-reported data type
of each point is mapped to the matching Ignition tag type (`Double` → `Float8`, etc.).
Double-clicking a `BinaryOutput<N>` row in a dashboard pre-fills the CROB popup with that
index. A device is skipped once the provider already holds at least as many of its points
as the browse returns — delete the device's folder in the Designer to force a re-import,
or delete `_TagSync_` to stop importing altogether. Progress and failures are logged on
the gateway under the `phenix.tag-sync` logger.

The overview table lists devices straight from the gateway's device connections
(`system.device.listDevices`), so it populates even before tags import; the IP/port
columns fill in from each device's `_Diagnostics_` tags once those exist.

### Browser auto-open

With `open_client` (and on every `type: perspective` host) the boot script registers a
`phenix-perspective` scheduled task that opens the HMI URL at the console user's logon —
Windows 10 doesn't reliably run Startup-folder shortcuts, but an interactive logon task
fires in the logged-on session. The task is also kicked once right after the gateway is
configured, with a short delay so the gateway web server is up; if nobody is logged on
yet, an `HKLM ...\CurrentVersion\Run` entry opens it at first logon instead. This needs
an auto-logon (or logged-in) interactive session and a default browser on the image.

## Dependencies

### Images

- ignition: Ignition version 8.3 Gateway installed as a service on a Windows VM. Other versions of ignition _may_ work but are untested.
- RTU/outstation VMs (e.g. ot-sim based) listening for DNP3 on the configured port.
