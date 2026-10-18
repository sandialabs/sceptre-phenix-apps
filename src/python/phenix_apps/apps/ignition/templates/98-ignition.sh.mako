#!/bin/bash
# phenix ignition app (gwbk restore, gateway start)
set -euo pipefail

staged=/restore.gwbk
data=/opt/ignition/data

echo "[ IGNITION ] Stopping gateway"
systemctl stop ignition || true

if [ -f "$staged" ]; then
    echo "[ IGNITION ] Staging restore of $staged"
    # the gateway restores a timestamped __restore file found in its data dir on start
    mv "$staged" "$data/__restore_$(date +%s%3N).gwbk"
fi

echo "[ IGNITION ] Starting gateway"
systemctl start ignition
echo "[ IGNITION ] configured!"
