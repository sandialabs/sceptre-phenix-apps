#!/bin/bash
printf "%s" "waiting for root broker"
time while ! ping -c 1 -n -w 1  ${rootbroker_ip} &> /dev/null; do 
    printf "%c" "."
done