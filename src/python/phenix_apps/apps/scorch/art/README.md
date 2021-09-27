# Atomic Red Team Component

```
type: art
exe:  phenix-scorch-component-art
```

It is assumed that the `goart` executable is present on the host running phenix
and in `PATH` so it can be found with `which`.

## Metadata Options

```
metadata:
  framework: <local path to framework executable (e.g. goart)>
  technique: <technique ID>
  testName: <name of technique test>
  testIndex: <index of technique test>
  inputs: <map of input key/value pairs>
  env: <map of environment variables>
  validator: <bash script to validate results>
  abortOnError: bool
  vms: <list of VM settings>
```

Only one of `testName` and `testIndex` needs to be provided. If both are
present, `testIndex` takes precedence. If neither are provided, index 0 will be
assumed.

`inputs` key/value pairs are used to fill in Atomic test variables.

`env` key/value pairs are merged into the execution environment Atomic tests are
executed in (e.g. if the command a test is executing also expects some env
variables to be present).

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

## Example Configuration

```
components:
  - name: T1190
    type: art
    metadata:
      framework: /phenix/share/bin/goart
      technique: T1190
      testIndex: 0 # 0 is the default
      vms:
        - hostname: kali-inet
          abortOnError: false # false is the default
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
          if [[ "$line" ]] == *"Session 1 created"* ]]; then
            echo "T1190 ($1) -- Success"
            exit 0
          fi
        done

        echo "T1190 ($1) -- Failure" >&2
        exit 1
```
