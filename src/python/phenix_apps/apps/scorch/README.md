# Scorch component concurrency

Use these components with the matching simultaneous-runs controller in
`sceptre-phenix`. `ComponentBase` accepts `--scorch-capabilities` without reading
an experiment and reports `{"scorchConcurrencyProtocol": 1}`. Its normal five
positional arguments remain unchanged.

The controller passes `PHENIX_SCORCH_EXECUTION_ID` and
`PHENIX_SCORCH_CONTROL_DIR`. In managed mode, `mm_init()` wraps minimega with
`ScopedCC`: local filter/prefix settings are applied under an advisory namespace
file lock immediately before each CC operation. Command submission ends before
response waiting starts, so a waiting component never holds the namespace lock.
All processes for an experiment must use the same controller host/directory.

Command prefixes include execution, run, component, loop, and count. Prefix
queries are normalized for existing utility callers. Namespace-wide command and
response deletion is translated to the component's prefix. A managed `cc` reset
does not clear another run's commands/responses. Without the execution ID,
components preserve their legacy standalone behavior.

Guest commands remain shared experiment actions. Use distinct files, ports,
service names, and stop/cleanup commands where simultaneous runs touch the same
VM. The controller rejects overlapping same-type runs for broad process-killing
components (`tcpdump`, `snort`, `ettercap`, `iperf`) and requires namespace
exclusivity for unrestricted/unknown components. An ordinary minimega client
that does not take this lock can still interfere with CC; avoid concurrent
namespace-wide resets outside managed Scorch.

Tests are in `tests/test_control.py`. They verify concurrent filter/prefix
submission, scoped resets, and release of the lock after a submission failure.
Guest execution, packet capture, and process cleanup still need validation on
the deployed minimega/VM environment.
