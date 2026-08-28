<%page args="url"/>\
# Startup-folder shortcuts don't reliably run on Windows 10, so open the
# client via an interactive logon task instead (kicked once right away if
# someone is already logged on). The delay gives the gateway time to start.
$openUrl = '${url}'
$openArg = "-NoProfile -WindowStyle Hidden -Command `"Start-Sleep 30; Start-Process '$openUrl'`""
$user = (Get-CimInstance Win32_ComputerSystem).UserName
if ($user) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $openArg
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
    Register-ScheduledTask -TaskName 'phenix-perspective' -Action $action `
        -Trigger $trigger -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName 'phenix-perspective'
    Write-Output "[ignition] perspective client opens at logon for $user"
} else {
    New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' `
        -Name 'phenix-perspective' -Value "powershell.exe $openArg" `
        -PropertyType String -Force | Out-Null
    Write-Output "[ignition] no interactive session; perspective client opens at first logon"
}
