# pcap Component

Collects PCAPs from VMs via minimega's `capture pcap` API.

```
type:   pcap
exe:    phenix-scorch-component-pcap
stages: start, stop
```

## Metadata Options

```yaml
metadata:
  convertToJSON: <bool>  # (Optional) Create .jsonl (JSON Lines) files from PCAPs using tshark. Default: false
  create_merged_pcap: <bool>  # (Optional) Merge all PCAP files into a single file using 'mergecap'. Default: false
  filter: <string>  # (Optional) bpf filter expression, as you'd use with tcpdump
  snaplen: <integer>  # (Optional) Maximum size of packets in capture
  vms:
    - hostname: <string>  # (REQUIRED) Hostname of VM from topology to capture traffic from
      interface: <integer or string>  # (Optional) Name or index of interface on VM to capture traffic on. Default: 0 (the first non-management interface)
  filebeat.inputs:  # NOTE: if filebeat is configured, ensure convertToJSON is true
    - type: log
      enabled: true
      paths:
      - *.pcap.jsonl
      processors:
      - decode_json_fields:
          fields:
            - message
          target: scorch.pcap
      - drop_event:
        when:
          has_fields:
            - scorch.pcap.index._type
      - drop_fields:
          fields: ['message']
      - timestamp:
          field: scorch.pcap.timestamp
          layouts:
            - 'UNIX_MS'
```

The `filter` and `snaplen` options are optional. `filter` and `snaplen` will also apply to ALL captures on all VMs. Not sure how to work around this limitation at the moment.

The `convertToJSON` creates `.jsonl` (JSON Lines format) files from the PCAP files. This option is important if Filebeat is going to be used to process the results of the traffic capture to send to Elastic. By default it is disabled since it can take a while to complete. If `convertToJSON` is `true`, then it is assumed that the `tshark` executable is present on the host running this component.

The `create_merged_pcap` option will merge all of the PCAP files into a single file using `mergecap`. This simplifies analysis when a large number of hosts are being captured and the capture duration is low, or vice-versa. If `create_merged_pcap` is `true`, then it is assumed that the `mergecap` executable is present on the host running this component (this is typically included when installing tshark or Wireshark). By default, this is set to `false`, since the resulting file can be quite large for long-running captures.

The `filebeat.inputs` section above can be blindly copied into user's own config and used as-is, or users can choose to change target field names if the ones used above aren't suitable.

## Example Configuration

```yaml
components:
  - name: pcap-example
    type: pcap
    metadata:
      convertToJSON: true
      create_merged_pcap: true
      filter: "not localhost"
      snaplen: 1500
      vms:
        - hostname: rtu-1  # defaults to interface 0
        - hostname: rtu-2
          interface: eth0
        - hostname: scada
          interface: 1
      filebeat.inputs:  # NOTE: if filebeat is configured, ensure convertToJSON is true
        - type: log
          enabled: true
          paths:
          - *.pcap.jsonl
          processors:
          - decode_json_fields:
              fields:
                - message
              target: scorch.pcap
          - drop_event:
            when:
              has_fields:
                - scorch.pcap.index._type
          - drop_fields:
              fields: ['message']
          - timestamp:
              field: scorch.pcap.timestamp
              layouts:
                - 'UNIX_MS'
```
