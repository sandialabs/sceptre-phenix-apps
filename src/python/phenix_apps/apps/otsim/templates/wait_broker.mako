#!/bin/bash
# wait for the HELICS broker to accept connections
printf "%s" "waiting for broker"
time while ! timeout 1 bash -c "exec 3<> /dev/tcp/${broker_host}/${broker_port}" &> /dev/null; do
    printf "%c" "."
    sleep 1
done
