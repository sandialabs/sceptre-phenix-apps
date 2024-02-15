Import-Module Wasp
Import-Module C:\Windows\System32\UIAutomation.0.8.7B3.NET35\UIAutomation.dll

function Show-Sleep($seconds) {
    $doneDT = (Get-Date).AddSeconds($seconds)
    while($doneDT -gt (Get-Date)) {
        $secondsLeft = $doneDT.Subtract((Get-Date)).TotalSeconds
        $percent = ($seconds - $secondsLeft) / $seconds * 100
        Write-Progress -Activity "Sleeping" -Status "Sleeping..." -SecondsRemaining $secondsLeft -PercentComplete $percent
        [System.Threading.Thread]::Sleep(500)
    }
    Write-Progress -Activity "Sleeping" -Status "Sleeping..." -SecondsRemaining 0 -Completed
}

## Waiting for startup.ps1 to finish
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

Echo ''
Echo 'Waiting for MySCADA server to finish configuration...'
Show-Sleep(200)
Echo ''
Echo 'Opening MySCADA Interface...'
% for scada_addr in scada_ips:
Start-Process -FilePath "C:\Program Files (x86)\Mozilla Firefox\firefox.exe" -ArgumentList ${scada_addr} -WindowStyle Maximized
% endfor
Echo 'Done.'

Echo 'Removing Users share...'
net share Users /DELETE | Out-Null
Echo 'Done.'

Echo 'Removing UIA log...'
Remove-Item C:\Users\wwuser\Documents\UIA.log
Echo 'Done.'
