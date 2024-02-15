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

while ($true)
{
	Start-Sleep -s ${connect_interval}
	% for fd in eng_fd:
	    % for iface in fd.topology.network.interfaces:
		% if not iface.type == 'serial' and iface.vlan.lower() != 'mgmt':
$winscp = Start-Process -FilePath "C:\Program Files (x86)\WinSCP\WinSCP.exe" -ArgumentList "/console /open -hostkey=* scp://root:SiaSd3te@${iface.address}" -passthru
Start-Sleep -s 5
Stop-Process $winscp.Id
	       % endif
	    % endfor
	% endfor
}
