# pipe Component

Implements minimega 'pipe' API as a SCORCH component.

```
type:   pipe
exe:    phenix-scorch-component-pipe
stages: start, cleanup
```

> [!NOTE]
> - Creation: A named pipe is created automatically on its first read, write,
>   or mode selection.  
> - Message Delivery: Messages written to a pipe are delivered to any attached
>   readers according to the pipe's current mode.  
> - Buffering: Messages are not buffered. If no readers are present, messages
>   are discarded. This means a new reader will only receive messages from the
>   moment it attaches to the pipe onward.  
> - Naming: Named pipes are unique to their namespace.

> [!CAUTION]
> The `via`, `mode`, and `log` options are considered top-level commands and
> if used, will be executed *before* any data is written to the pipe

## Metadata Options

```yaml
metadata:
  pipe: <string>  # (REQUIRED) Name of pipe
  data: <string>  # (Optional) Data to write to pipe
  via:  <string>  # (Optional) Sets a program as a via, which processes all data written to the pipe before sending to readers
  mode: <string>  # (Optional) Sets the delivery mode for the pipe (all|round-robin|random)
  log:  <bool>    # (Optional) Enables or disables logging for the pipe
```

## Example Configurations

<details>
  <summary>Send a JSON string message to a pipe</summary>

  ```yaml
  components:
    - name: pipe-example
      type: pipe
      metadata:
        pipe: foo
        data: '{\"duration\":0}'
  ```
</details>

<details>
  <summary>Set a via command for a pipe</summary>

  ```yaml
  components:
    - name: pipe-example-via
      type: pipe
      metadata:
        pipe: bar
        via: sed -u 's/test/woot/'
  ```
</details>

<details>
  <summary>Set the mode for a pipe</summary>

  ```yaml
  components:
    - name: pipe-example-mode
      type: pipe
      metadata:
        pipe: baz
        mode: random
  ```
</details>

<details>
  <summary>Enable the log for a pipe</summary>

  ```yaml
  components:
    - name: pipe-example-log
      type: pipe
      metadata:
        pipe: whizbang
        log: true
  ```
</details>

<details>
  <summary>Pipe example *</summary>

  ```yaml
  components:
    - name: pipe-example-*
      type: pipe
      metadata:
        pipe: foobarbazwhizbang
        data: '{\"duration\":0}'
        via: sed -u 's/test/woot/'
        mode: all
        log: true
  ```
</details>
