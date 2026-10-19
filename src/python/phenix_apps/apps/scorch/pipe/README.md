# pipe Component

Implements minimega 'pipe' API as a SCORCH component.

```
type:   pipe
exe:    phenix-scorch-component-pipe
stages: start, cleanup
```

| Stage | What it does |
|---|---|
| `start` | In this order, each only if set: sets `via`, sets `mode`, turns `log` on or off, then writes `data` to `pipe`. |
| `cleanup` | Deletes the pipe (minimega's `clear pipe`), which drops its `via`, `mode` and `log` settings and disconnects its readers. minimega refuses while any writer is still open. |

> [!IMPORTANT]
> A `via` program runs on the phenix host. To lock this down, set
> `PHENIX_SCORCH_HOST_VALIDATORS=0` in the phenix environment; a `via` then
> fails the component.

## Before you start

- A reader must already be attached to the pipe when `start` runs. minimega
  does not buffer messages, so a message written with no reader attached is
  discarded, and a new reader only sees messages sent after it attaches.
- `cleanup` deletes the pipe, so close every writer first (minimega refuses to
  delete a pipe with open writers) and reattach readers afterwards; a reader
  attached before `cleanup` is disconnected and does not see the next loop.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `pipe` | word (no whitespace or quotes) | yes | | Pipe name |
| `data` | string | no | | Message to write. No single quotes, no line breaks. Backslashes are sent as written. Must be a string, so put JSON in quotes in YAML. An empty string is the same as leaving it out |
| `via` | command line | no | | Program (with arguments) on the phenix host that every message passes through. It is started for each message and reader, must read stdin to the end and then exit. One line. An empty string is the same as leaving it out |
| `mode` | `all`, `round-robin` or `random` | no | `all` (minimega's default) | How messages are shared between readers. An empty string is the same as leaving it out |
| `log` | bool | no | unchanged | `true` or `false` turns minimega's logging of the pipe's messages on or off |

## Examples

<details>
  <summary>Send a JSON message to a pipe</summary>

  ```yaml
  components:
    - name: announce-run
      type: pipe
      metadata:
        pipe: run-control
        data: '{"event":"start","duration":300}'
  ```
</details>

<details>
  <summary>Set a via program for a pipe</summary>

  ```yaml
  components:
    - name: pipe-example-via
      type: pipe
      metadata:
        pipe: bar
        via: sed s/test/woot/
  ```
</details>

<details>
  <summary>Set the delivery mode for a pipe</summary>

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
  <summary>Turn on logging for a pipe</summary>

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
  <summary>All options together: round-robin work queue with a via program and logging</summary>

  ```yaml
  components:
    - name: work-queue
      type: pipe
      metadata:
        pipe: jobs
        mode: round-robin
        log: true
        via: sed s/test/woot/
        data: test job
  ```
</details>

To check a config before an experiment: `phenix-scorch-validate scenario.yaml`

## Troubleshooting

| Error or symptom | Cause and fix |
|---|---|
| `pipe: Field required` | `pipe` is missing. |
| `pipe: String should match pattern '^[^\s'"]+$'` | The pipe name has whitespace or quotes. |
| `data: String should match pattern '^[^'\r\n]+$'` | `data` has a single quote or a line break. Use double quotes inside the message instead. |
| `data: Input should be a valid string` | `data` is a mapping, list, number or `true`/`false`. Quote it so it is sent as written. |
| `mode: Input should be 'all', 'round-robin' or 'random'` | A misspelt `mode`. |
| `log: Input should be a valid boolean, unable to interpret input` | `log` must be `true` or `false`. |
| the reader never gets the message | Nothing was reading the pipe when `start` ran, or the reader is in another namespace. |
| messages arrive changed or not at all after setting `via` | minimega starts the `via` program for each message and each reader, feeds it the message on stdin and waits for it to exit. The program must read stdin to the end and exit, and must not keep running. Plain `sed s/test/woot/` works. |

## Limitations

- `via` runs a program on the phenix host with minimega's privileges, once per
  reader, so side effects repeat; only use programs you trust.
- `data` is written once, in `start`; there is no way to send at other stages.
- `cleanup` deletes the pipe, including settings made by something else, and fails while a writer is open.
