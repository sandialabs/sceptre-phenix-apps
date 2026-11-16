# phenix harden: ${hostname}. Runs once at boot, then deletes itself.
$ErrorActionPreference = 'Stop'

# phenix core's startup script reboots the VM until this is done, and writes
# the autologon password just before; wait for the boot after its last reboot.
$phenix = Get-Item -Path 'HKLM:\Software\phenix' -ErrorAction SilentlyContinue
if (-not $phenix -or $phenix.GetValue('startup') -ne 'done') { exit }

$result = 'C:\phenix\harden.result'

try {
    # The WinNT provider works on every Windows build; Set-LocalUser does not.
    $computer = [ADSI]"WinNT://$env:COMPUTERNAME,computer"
    $users = @{}
    foreach ($child in $computer.Children) {
        if ($child.SchemaClassName -eq 'user') { $users[[string]$child.Name] = $child }
    }

    # Winlogon takes DefaultPassword from this key, where phenix's startup script puts it.
    $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    $logon = Get-ItemProperty -Path $winlogon
    $autoUser = [string]$logon.DefaultUserName
    $autoDomain = [string]$logon.DefaultDomainName
    # The autologon account, while autologon is on, is local when its domain is unset, '.', or this machine.
    $autoIsLocal = [string]$logon.AutoAdminLogon -eq '1' -and $autoUser -and (-not $autoDomain -or $autoDomain -eq '.' -or $autoDomain -ieq $env:COMPUTERNAME)

% if autologon == "keep":
% for name in remove_users:
    if ($autoIsLocal -and $autoUser -ieq '${name}') {
        throw "cannot remove the autologon user ${name} while autologon is kept"
    }
% endfor
% endif

% for name, password in users.items():
    if (-not $users.ContainsKey('${name}')) {
        throw "no local user ${name}"
    }
    $password = '${password}'
    $users['${name}'].SetPassword($password)
    $users['${name}'].SetInfo()
    Write-Output 'set password: ${name}'
% if autologon == "keep":
    if ($autoIsLocal -and $autoUser -ieq '${name}') {
        Set-ItemProperty -Path $winlogon -Name DefaultPassword -Value $password
        Write-Output 'updated autologon password: ${name}'
    }
% endif
    # A service that logs on as the account stores its own copy of the password.
    $services = Get-CimInstance Win32_Service -Filter "StartName='.\\${name}' OR StartName='$env:COMPUTERNAME\\${name}'"
    foreach ($service in @($services)) {
        $changed = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{ StartPassword = $password }
        if ($changed.ReturnValue -ne 0) {
            throw "update the logon password of service $($service.Name): error $($changed.ReturnValue)"
        }
        Write-Output "updated service logon password: $($service.Name)"
    }
% endfor

% for name in remove_users:
    if ($users.ContainsKey('${name}')) {
        # Remove the profile too, unless the account is logged on and holds it open.
        $sid = (New-Object Security.Principal.SecurityIdentifier($users['${name}'].objectSid.Value, 0)).Value
        Get-CimInstance Win32_UserProfile -Filter "SID='$sid' AND Loaded=False" | Remove-CimInstance
        $computer.Delete('user', '${name}')
        Write-Output 'removed user: ${name}'
    } else {
        Write-Output 'no such user, nothing to remove: ${name}'
    }
% endfor

% if autologon == "disable":
    Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '0'
    Remove-ItemProperty -Path $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
    Write-Output 'autologon disabled'
% endif

    Set-Content -Path $result -Value 'ok'
} catch {
    # A COM error message spans lines; keep the result to one.
    $line = 'harden: ' + ("$_" -replace '\s+', ' ').Trim()
    Set-Content -Path $result -Value $line
    Write-Output $line
} finally {
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
