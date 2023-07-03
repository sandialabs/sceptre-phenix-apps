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

C:\myscada.exe
