function Phenix-StartupComplete {
  $key = Get-Item -LiteralPath 'HKLM:\Software\phenix' -ErrorAction SilentlyContinue

  if ($key) {
    $val = $key.GetValue('startup')

    if ($val) {
      return $val -eq 'done'
    }

    return $false
  }

  return $false
}
while (-Not (Phenix-StartupComplete)) {
    Start-Sleep -s 30
}

% for fd in eng_fd:
new-item -path "HKCU:\Software\SimonTatham\"
new-item -path "HKCU:\Software\SimonTatham\PuTTY\"
new-item -path "HKCU:\Software\SimonTatham\PuTTY\Sessions"
new-item -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.hostname}"
    % for iface in fd.topology.network.interfaces:
        % if not iface.type == 'serial' and iface.vlan.lower() != 'mgmt':
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.hostname}" -name Hostname -value ${iface.address}
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.hostname}" -name Protocol -value telnet
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.hostname}" -name PortNumber -value 1337 -type DWord
<% break %>
        % endif
    % endfor
% endfor

