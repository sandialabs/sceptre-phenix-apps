#!/bin/bash

service dnsmasq stop
chattr +i /etc/resolv.conf

service dnsmasq start
