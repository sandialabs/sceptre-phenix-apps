# Builtin Scale Plugin

The **Builtin Plugin** is the default plugin for the Scale App. It provides generic infrastructure scaling capabilities, allowing users to deploy a specified number of Virtual Machines (VMs) or calculate the number of VMs needed to host a specific volume of containers.

## Configuration

The plugin is configured via the `profiles` list in the Scale App metadata.

### Fields

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `count` | Integer | `1` | The number of VMs to deploy. Ignored if `containers` > 0. |
| `containers` | Integer | `0` | The total number of application containers required. |
| `containers_per_node` | Integer | `0` | The number of containers to pack onto a single VM. |
| `hostname_prefix` | String | `"node"` | The prefix used for generating VM hostnames (e.g., `node-1`). |
| `node_template` | Dict | `{}` | Overrides for VM hardware (`cpu`, `memory`, `image`, `network`). |
| `container_template`| Dict | `{}` | Configuration for containers (`rootfs`, `networks`, `gateway`, `cpu`, `memory`). |

## Scaling Modes

### 1. VM Scaling (Direct)

Use this mode when you want a specific number of VMs.

```yaml
- name: my-cluster
  plugin: builtin
  count: 5
  # Result: 5 VMs (node-1 to node-5)
```

### 2. Container Scaling (Calculated)

Use this mode when you have a target number of containers and want the plugin to calculate the infrastructure requirements.

**Formula:** `Node Count = ceil(containers / containers_per_node)`

```yaml
- name: app-cluster
  plugin: builtin
  containers: 105
  containers_per_node: 10
  # Result: 11 VMs
  # - Nodes 1-10: 10 containers each
  # - Node 11: 5 containers
```

## Versions

The plugin supports versioning to demonstrate backward compatibility or experimental features.

*   **`1.0.0`** (Default): Standard behavior.
*   **`2.0.0`**: Example version that changes the hostname prefix to `v2-node-`.

To use a specific version:
```yaml
plugin:
  name: builtin
  version: "2.0.0"
```

## Testing

### Unit Tests
Tests for the Builtin plugin are included in the main Scale app test suite: `phenix_apps/apps/scale/tests/test_scale.py`. These tests verify configuration validation and node/container calculations.

To run the tests:
```bash
pytest phenix_apps/apps/scale/tests/test_scale.py
```

### Dry-Run
The `phenix_apps/apps/scale/tests/test_scale_input.yaml` file contains example profiles for the Builtin plugin (`builtin-profile-v1` and `builtin-profile-latest`).

To verify the plugin output:
```bash
phenix-app-scale configure --dry-run < phenix_apps/apps/scale/tests/test_scale_input.yaml
```