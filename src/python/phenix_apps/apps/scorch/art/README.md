# Atomic Red Team Component

The Atomic Red Team (ART) component provides a means to connect scorch experiment configuration files to action Atomic Red Team attacks - using the ATT&CK framework. This provides a programmatic way to run attacks via experiments.

#The goart executable:
https://github.com/activeshadow/go-atomicredteam

#Reference Techniques, Index and Requirements:
https://github.com/redcanaryco/atomic-red-team/tree/master/atomics

```
type: art
exe:  phenix-scorch-component-art
```

It is assumed that the `goart` executable is available on the target VM in either the default path or the path specified in the configuration file. The component will verify the binary exists and is executable on the VM before attempting to run it.



## Executable Requirement

The `goart` binary must be injected, downloaded or preloaded into each target VM. The examples below demonstrate injecting the binary/executable via the topology config.

topology.yml:

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

Scenario File (Scenario-Scorch.yml)
## Metadata Options

```yaml
metadata:
  technique: <technique ID> *REQUIRED
  testName: <name of technique test> *ONLY REQUIRED if testIndex is not present
  testIndex: <index of technique test> *ONLY REQUIRED if testName is not present
  goartPath: <path to goart executable on the VM> (optional) default: /phenix/art/goart or C:/phenix/art/goart.exe
  outputPath: <path to write goart output on the VM (optional, default: /phenix/art or /tmp)>
  execWaitSeconds: <seconds to wait after execution before retrieving results (optional, default: 5)>
  env: <map of environment variables>
  validator: <bash script to validate results>
  abortOnError: bool
  vms: <list of VM settings> *REQUIRED
```

Only one of `testName` and `testIndex` needs to be provided. If both are
present, `testIndex` takes precedence.

`goartPath` overrides the default goart binary path on the VM. Defaults to
`C:/phenix/art/goart.exe` for Windows and `/phenix/art/goart` for Linux.

`outputPath` overrides the directory where goart writes its JSON results on the
VM. Defaults to `/phenix/art` for Windows and `/tmp` for Linux. Note that for
Windows, this path must be accessible to the miniccc process.

`execWaitSeconds` controls how long the component waits after goart finishes
before attempting to retrieve the results file. Increase this for techniques
that have significant post-execution activity.

`env` key/value pairs are merged into the execution environment Atomic tests are
executed in.

`validator` script should expect to be passed the hostname of the VM as the only
command line argument and the `.Executor.ExecutedCommand.results` portion of the
JSON output of the executed Atomic test as STDIN. If the script exits with zero
then it's assumed that it passed. If it exits with non-zero then it's assumed
that it failed. For exit zero, anything passed to STDOUT will be streamed to the
UI, and for exit non-zero anything passed to STDERR will be streamed to the UI.
If exit non-zero and `abortOnError` is true, then the component exits as failed.
If no validator is provided then it is assumed the test succeeded if the atomic
executor exits cleanly.

`vms` is a list of settings per VM to execute the test on.

## VM Settings

```yaml
vms:
  - hostname: <VM hostname> *REQUIRED
    inputs: <map of input key/value pairs> *REQUIRED as per technique information. Refer to Atomic Red Team Github.
    env: <map of environment variables>
    abortOnError: bool
```

`inputs` key/value pairs are used to fill in Atomic test variables for that
specific VM.

## Example Configuration

```yaml
components:
  - name: T1006
    type: art
    metadata:
      technique: T1006
      testIndex: 0
      execWaitSeconds: 10
      vms:
        - hostname: IT-ws10
          inputs:
            volume: "c:"
        - hostname: IT-ws11
          inputs:
            volume: "c:"
```

With optional overrides:

```yaml
components:
  - name: T1190
    type: art
    metadata:
      technique: T1190
      testIndex: 0
      goartPath: /custom/path/goart.exe
      outputPath: /custom/output
      execWaitSeconds: 15
      vms:
        - hostname: kali-inet
          abortOnError: false
          inputs:
            rhost: 172.29.0.25
            lhost: 1.2.3.4
        - hostname: kali-dmz
          abortOnError: true
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
