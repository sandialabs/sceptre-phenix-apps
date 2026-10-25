# Caldera Component

```
type: caldera
exe:  phenix-scorch-component-caldera
```

Execute operation in Caldera by calling the REST API (via minimega cc).
Adversary and fact source must already be present and loaded in Caldera server
(this can be done via the `caldera` phenix app or via custom injections in the
topology).

This component creates and starts a new operation using the given adversary,
facts, and planner, waits for the operation to complete, gets the operation
report, and writes the report to the appropriate directory for the given Scorch
run, loop, and count. It does the same work in every stage it is listed in
(`configure`, `start`, `stop`, `cleanup`), so list it in one stage only.

## Examples

Adversary and fact source by name, default planner:

```yaml
components:
  - name: foobar # also the name of the operation in Caldera
    type: caldera
    metadata:
      server: mallory
      adversary: superbad
      facts: recon
```

All by UUID, which skips the ID lookups and runs faster:

```yaml
components:
  - name: uuid-op
    type: caldera
    metadata:
      server: mallory
      adversary: 5d3e170e-f1b8-49f9-9ee1-c51605552a08
      facts: 6c4a9f2e-8a3c-4d6e-b1a7-2f9d5e0c1b34
      planner: aaa7c857-37a0-4c4a-85f7-4e9f7f30e31a
```

## Fields

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `server` | yes | none | Hostname of the VM running the Caldera server. |
| `adversary` | yes | none | Adversary name or UUID; must already be in Caldera. |
| `facts` | yes | none | Fact source name or UUID; must already be in Caldera. |
| `planner` | no | the `phenix` planner UUID | Planner name or UUID (`atomic` and `batch` are common). |

Names and UUIDs may contain any printable characters except `'`, which is
rejected because the REST API JSON body is written inside a single-quoted shell
string (the values themselves are JSON-encoded). Unknown keys are accepted without a warning.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `server: Field required` (or `adversary`, `facts`) | A required field is missing. | Add it to `metadata`. |
| `adversary: String should match pattern` | The value has a `'`, a line break or another control character. | Use the plain adversary name or its UUID. |
| `unable to find '<name>' adversary` | No such name in Caldera. | Load it first, or pass its UUID. |
| `failed to make API call for ...` | The Caldera API call on `server` returned non-zero. | Check the `cc` command output and that Caldera is running on `server`. |

## TODO

Consider using minimega's port forwarding capability (via cc) to make API calls
directly. This would make the component run faster, but the current approach may
be easier for users to debug since all commands and responses are tracked via
minimega cc.
