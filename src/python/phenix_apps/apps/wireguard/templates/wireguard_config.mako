[Interface]
PrivateKey = ${wireguard['interface']['private_key']}
Address = ${wireguard['interface']['address']}
% if 'listen_port' in wireguard['interface']:
ListenPort = ${wireguard['interface']['listen_port']}
% endif

% for peer in wireguard['peers']:
[Peer]
PublicKey = ${peer['public_key']}
AllowedIPs = ${peer['allowed_ips']}
% if 'server_endpoint' in peer:
Endpoint = ${peer['server_endpoint']}
% endif
% if 'keepalive' in peer:
PersistentKeepalive = ${peer['keepalive']}
% endif
% endfor
