#!/bin/bash
# phenix ignition app (perspective client)

echo "[ IGNITION ] Starting perspective viewer"
until [ "$(curl -s -o /dev/null -w '%{http_code}' '${url}')" = 200 ]; do
    echo "[ IGNITION ] Gateway not ready yet, retrying in 10 seconds..."
    sleep 10
done

echo "[ IGNITION ] Gateway ready, starting firefox"
firefox '${url}' &
echo "[ IGNITION ] Gateway ready, firefox started, all done!"
