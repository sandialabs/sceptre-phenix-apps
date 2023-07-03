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
new-item -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.name}"
    % for iface in fd.interfaces:
        % if not iface.type_ == 'serial' and iface.vlan_alias.lower() != 'mgmt':
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.name}" -name Hostname -value ${iface.ipv4_address}
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.name}" -name Protocol -value telnet
new-itemproperty -path "HKCU:\Software\SimonTatham\PuTTY\Sessions\${fd.name}" -name PortNumber -value 1337 -type DWord
<% break %>
        % endif
    % endfor
% endfor

