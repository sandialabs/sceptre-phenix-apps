#!/bin/bash
# wait for the root broker to accept connections on its default ZMQ port
printf "%s" "waiting for root broker"
time while ! timeout 1 bash -c "exec 3<> /dev/tcp/${rootbroker_ip}/23404" &> /dev/null; do
    printf "%c" "."
    sleep 1
done
