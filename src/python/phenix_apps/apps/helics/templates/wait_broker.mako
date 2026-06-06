#!/bin/bash
# Wait for the root broker to actually accept connections, not merely respond
# to ping (host reachable != helics_broker listening). Probe the broker
# webserver port (8080) via bash /dev/tcp. Pairs with always enabling the root
# broker webserver (see broker.mako).
printf "%s" "waiting for root broker"
time until (exec 3<>"/dev/tcp/${rootbroker_ip}/8080") 2>/dev/null; do
    printf "%c" "."
    sleep 1
done
