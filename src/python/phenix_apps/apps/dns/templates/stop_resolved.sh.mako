#!/bin/bash

systemctl disable systemd-resolved.service
systemctl stop systemd-resolved

# bash -c "cat >> /etc/NetworkManager/NetworkManager.conf" << 'EOL'
# [main]
# dns=default
# EOL

# rm /etc/resolv.conf
mv /etc/resolve.conf /etc/resolve.conf.bak

# service NetworkManager restart
