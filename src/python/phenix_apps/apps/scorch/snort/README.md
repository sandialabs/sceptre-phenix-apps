# Snort

## Metadata Options

```
metadata:
  hostname: detector
  sniffInterface: eth0
  waitDuration: 30
  configs:
  - name: snort
    src: /phenix/topologies/snort-test/configs/snort.conf
    dst: /etc/snort/snort.conf
  - name: emotet
    src: /phenix/topologies/snort-test/configs/emotet.rules
    dst: /etc/snort/rules/emotet.rules
  scripts:
    configSnort:
      executor: bash
      script: /phenix/topologies/snort-test/scripts/configure-snort.sh
```
