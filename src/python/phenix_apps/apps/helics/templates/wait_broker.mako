#!/bin/bash
# wait for the root broker to be up and accepting connections
printf "%s" "waiting for root broker"
time while ! nc -z -w1 ${rootbroker_ip} 23404 &> /dev/null; do
    printf "%c" "."
done
