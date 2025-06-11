# Caldera Component

```
type: caldera
exe:  phenix-scorch-component-caldera
```

Execute operation in Caldera by calling the REST API (via minimega cc).
Adversary and fact source must already be present and loaded in Caldera server
(this can be done via the `caldera` phenix app or via custom injections in the
topology).

This component will error out if adversary, facts, or planner do not exist in
Caldera already. This component will also run faster if UUIDs for adversary,
facts, and planner are used instead of names, because additional API calls (via
minimega cc commands) will be skipped to look up IDs.

This component creates and starts a new operation using the given adversary,
facts, and planner, waits for the operation to complete, gets the operation
report, and writes the report to the appropriate directory for the given Scorch
run, loop, and count.

## Example Configuration

```yaml
components:
  - name: foobar # this will also be the name of the operation in Caldera
    type: caldera
    metadata:
      server: mallory     # hostname of Caldera server to operate from
      adversary: superbad # can be adversary name or UUID (must already be in Caldera)
      facts: recon        # can be fact source name or UUID (must already be in Caldera)
      planner: atomic     # this is the default (other popular option is `batch`) (can also be UUID)
```

## TODO

Consider using minimega's port forwarding capability (via cc) to make API calls
directly. This would make the component run faster, but the current approach may
be easier for users to debug since all commands and responses are tracked via
minimega cc.
