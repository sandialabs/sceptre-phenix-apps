# phēnix Apps

[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A collection of standard applications and Scorch components designed for use with [phēnix](https://github.com/sandialabs/sceptre-phenix).

## 📖 Overview

This repository contains the source code for official phēnix apps. These apps adhere to the phēnix App Contract:

1.  Accept the **stage** as a single command-line argument.
2.  Accept the **experiment JSON** over `STDIN`.
3.  Return the updated **experiment JSON** over `STDOUT`.
4.  Write structured **JSON logs** to `stderr` (or the file specified by `PHENIX_LOG_FILE`).

## 🚀 Getting Started

### Prerequisites

*   Python 3.12+
*   Go 1.24+ (for Go-based apps)
*   `make`

### Installation

To install the Python apps and development dependencies in editable mode:

```bash
make install-dev
```

## 🛠️ Development

We use a `Makefile` to standardize development tasks.

```bash
# Development
make all         # Run all tools (format, lint, and test)
make check       # Run linters without fixing (for CI)
make format      # Format code (golangci-lint, ruff)
make lint        # Lint code and fix issues (golangci-lint, ruff, etc.)
make test        # Run unit tests

# Installation & Cleanup
make install-dev # Install development dependencies and tools
make install     # Install runtime dependencies
make clean       # Clean build artifacts
```

## Apps

| Application | Description |
| :--- | :--- |
| [caldera](src/python/phenix_apps/apps/caldera) | Runs operations and retrieves reports from a Caldera C2 server. |
| [helics](src/python/phenix_apps/apps/helics) | Configures and manages HELICS (Hierarchical Engine for Large-scale Infrastructure Co-Simulation) federates. |
| [mirror](src/go/cmd/phenix-app-mirror) | Configures cluster-wide packet mirroring to a target node using GRE or ERSPAN tunnels. |
| [otsim](src/python/phenix_apps/apps/otsim) | Generates configuration files for OT-sim simulations. |
| [protonuke](src/python/phenix_apps/apps/protonuke) | Injects command-line arguments for the `protonuke` agent service. |
| [scale](src/python/phenix_apps/apps/scale) | Deploys large-scale infrastructure and applications using a plugin architecture. |
| [sceptre](src/python/phenix_apps/apps/sceptre) | An integration application for the SCEPTRE emulation platform. |
| [scorch](src/python/phenix_apps/apps/scorch) | Orchestrates sequences of actions (components) for automated testing and validation. |
| [wind_turbine](src/python/phenix_apps/apps/wind_turbine) | **(Deprecated)** Use the `wind_turbine` plugin within the `scale` app instead. |
| [wireguard](src/python/phenix_apps/apps/wireguard) | Configures WireGuard VPN tunnels between nodes. |

## Scorch components

| Component | Description |
| :--- | :--- |
| [art](src/python/phenix_apps/apps/scorch/art) | Executes adversary emulation techniques using the Atomic Red Team (ART) framework. |
| [caldera](src/python/phenix_apps/apps/scorch/caldera) | Runs operations and retrieves reports from a Caldera C2 server. |
| [cc](src/python/phenix_apps/apps/scorch/cc) | Executes arbitrary shell commands on nodes via minimega's command and control. |
| [collector](src/python/phenix_apps/apps/scorch/collector) | Collects files from specified nodes for post-experiment analysis. |
| [disruption](src/python/phenix_apps/apps/scorch/disruption) | Simulates network disruptions like Denial of Service (DoS) attacks. |
| [ettercap](src/python/phenix_apps/apps/scorch/ettercap) | Runs the Ettercap suite for man-in-the-middle attacks. |
| [hoststats](src/python/phenix_apps/apps/scorch/hoststats) | Collects host performance statistics (CPU, memory, etc.). |
| [iperf](src/python/phenix_apps/apps/scorch/iperf) | Measures network performance between nodes using iperf. |
| [kafka](src/python/phenix_apps/apps/scorch/kafka) | Interacts with Apache Kafka topics. |
| [mm](src/python/phenix_apps/apps/scorch/mm) | Executes arbitrary minimega commands. |
| [opcexport](src/python/phenix_apps/apps/scorch/opcexport) | Exports data from an OPC-UA server. |
| [pcap](src/python/phenix_apps/apps/scorch/pcap) | Manages network packet captures (.pcap files) across the experiment. |
| [pipe](src/python/phenix_apps/apps/scorch/pipe) | Implements minimega 'pipe' API. |
| [providerdata](src/python/phenix_apps/apps/scorch/providerdata) | Collects and verifies data from pybennu providers, such as the RTDS or OPALRT. |
| [qos](src/python/phenix_apps/apps/scorch/qos) | Applies Quality of Service (QoS) rules (e.g., latency, packet loss) to interfaces. |
| [rtds](src/python/phenix_apps/apps/scorch/rtds) | Interacts with RTDS (Real Time Digital Simulator) systems. |
| [snort](src/python/phenix_apps/apps/scorch/snort) | Runs the Snort Intrusion Detection System on specified interfaces. |
| [tcpdump](src/python/phenix_apps/apps/scorch/tcpdump) | Captures network traffic using tcpdump. |
| [trafficgen](src/python/phenix_apps/apps/scorch/trafficgen) | Generates network traffic between specified source and destination nodes. |
| [vmstats](src/python/phenix_apps/apps/scorch/vmstats) | Collects detailed VM statistics from minimega. |
