## phenix ignition app (gwbk restore, gateway start)
$ErrorActionPreference = 'Stop'

$staged = 'C:\restore.gwbk'
$data = 'C:\Program Files\Inductive Automation\Ignition\data'

Write-Host "[ IGNITION ] Stopping gateway"
echo "[ IGNITION ] Stopping gateway"
# the service may still be starting at boot; give up quietly if it will not stop
$service = Get-Service -Name Ignition -ErrorAction SilentlyContinue
$deadline = (Get-Date).AddMinutes(5)
while ($service -and $service.Status -ne 'Stopped' -and (Get-Date) -lt $deadline) {
    Stop-Service -Name Ignition -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $service.Refresh()
}

if (Test-Path $staged) {
    Write-Host "[ IGNITION ] Staging restore of $staged"
    echo "[ IGNITION ] Staging restore of $staged"
    # the gateway restores a timestamped __restore file found in its data dir on start
    $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    Move-Item -Path $staged -Destination (Join-Path $data ("__restore_{0}.gwbk" -f $stamp)) -Force
}

Write-Host "[ IGNITION ] Starting gateway"
echo "[ IGNITION ] Starting gateway"
Start-Service -Name Ignition
Write-Host "[ IGNITION ] configured!"
echo "[ IGNITION ] configured!"
