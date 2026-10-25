# Atomic Red Team Component

The Atomic Red Team (ART) component provides a means to connect scorch experiment configuration files to action Atomic Red Team attacks - using the ATT&CK framework. This provides a programmatic way to run attacks via experiments.

The goart executable: https://github.com/activeshadow/go-atomicredteam

Reference techniques, indexes and requirements: https://github.com/redcanaryco/atomic-red-team/tree/master/atomics

```
type: art
exe:  phenix-scorch-component-art
```

It is assumed that the `goart` executable is available on the target VM in either the default path or the path specified in the configuration file. The component verifies the binary exists and is executable on the VM before running it.

## Executable Requirement

The `goart` binary must be injected, downloaded or preloaded into each target VM. These topology injections place it at the default paths.

Windows VMs:

```yaml
injections:
  - src: /phenix/injects/${BRANCH_NAME}/art/goart.exe
    dst: /phenix/art/goart.exe
```

Linux VMs:

```yaml
injections:
  - src: /phenix/injects/${BRANCH_NAME}/art/goart
    dst: /phenix/art/goart
```

## Examples

A technique run by test index on two Windows VMs:

```yaml
components:
  - name: T1006
    type: art
    metadata:
      technique: T1006
      testIndex: 0
      vms:
        - hostname: IT-ws10
          inputs:
            volume: "c:"
        - hostname: IT-ws11
          inputs:
            volume: "c:"
```

A technique run by test name, with a custom binary path, environment variables, per-VM inputs and a host-side validator:

```yaml
components:
  - name: T1190
    type: art
    metadata:
      technique: T1190
      testName: Exploit public-facing application
      goartPath: /custom/path/goart
      abortOnError: true
      env:
        LOG_LEVEL: debug
      vms:
        - hostname: kali-inet
          inputs:
            rhost: 172.29.0.25
            lhost: 1.2.3.4
        - hostname: kali-dmz
          env:
            PROXY: 10.0.0.1
          inputs:
            rhost: 10.11.12.13
            lhost: 172.29.0.25
      validator: |
        while read line; do
          if [[ "$line" == *"Session 1 created"* ]]; then
            echo "T1190 ($1) -- Success"
            exit 0
          fi
        done
        echo "T1190 ($1) -- Failure" >&2
        exit 1
```

## Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `technique` | string | required | ATT&CK technique ID, e.g. `T1006` or `T1003.001`. |
| `testName` | string | - | Name of the technique test. Required if `testIndex` is not set. |
| `testIndex` | integer >= 0 | - | Index of the technique test. Required if `testName` is not set. |
| `goartPath` | path | `/phenix/art/goart` (Linux), `C:/phenix/art/goart.exe` (Windows) | Path to the goart executable on the VM. Forward slashes only. |
| `env` | map | `{}` | Environment variables merged into the environment Atomic tests run in, for every VM. |
| `validator` | string | - | Shell script that validates the results (see below). |
| `abortOnError` | bool | `false` | Fail the component when the validator exits non-zero. |
| `vms` | list | required | VMs to run the test on (at least one). |

Only one of `testName` and `testIndex` needs to be provided. If both are present, `testIndex` takes precedence.

Each entry in `vms`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hostname` | string | required | VM hostname. |
| `env` | map | `{}` | Environment variables for this VM, after the component-wide `env`. |
| `inputs` | map | `{}` | Values for the Atomic test's input variables, as required by the technique. See the Atomic Red Team repository. |

`env` and `inputs` names are letters, digits, `_`, `.` and `-`, not starting with a digit. Their values go on the goart command line, so they cannot contain whitespace, quotes, backslashes, backticks or any of `$ ; & | < >`.

The `validator` script is passed the hostname of the VM as its only command line argument and the `.Executor.ExecutedCommand.results` portion of the JSON output of the executed Atomic test as STDIN. If the script exits with zero then it's assumed that it passed. If it exits with non-zero then it's assumed that it failed, and if `abortOnError` is true the component exits as failed. If no validator is provided then it is assumed the test succeeded if the atomic executor exits cleanly.

> [!IMPORTANT]
> Validators run as shell scripts on the phenix host, not in the VM. To lock
> this down, set `PHENIX_SCORCH_HOST_VALIDATORS=0` in the phenix environment;
> each validator is then skipped with a warning and the result is not validated.

Results are saved as `<hostname>.json` in the component's output directory.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `no technique test configured (set testName or testIndex)` | Neither `testName` nor `testIndex` is set. | Set one of them. |
| `vms: List should have at least 1 item` | `vms` is missing or empty. | List at least one VM. |
| `goart not found or not executable at ...` | The binary is not on the VM at that path. | Inject it via the topology or set `goartPath`. |
| `failed to get results file from <host>` | goart did not write its results, or the transfer failed. | Run goart by hand on the VM and check the technique's requirements. |
| `technique` or `env`/`inputs` name rejected | It contains characters that would break the command line. | Use a plain ID or name. |
| A value is rejected | It contains whitespace, a quote, a backslash or one of `` ` $ ; & | < > ``. | Pass a simpler value. |
| `results validation failed` | The validator exited non-zero. | Check the validator's output; with `abortOnError: false` the run continues. |
| Validator skipped with a warning | `PHENIX_SCORCH_HOST_VALIDATORS=0` is set. | Unset it to run validators. |
