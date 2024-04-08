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
Echo 'Configuring Historian...'
    
$ErrorActionPreference = [System.Management.Automation.ActionPreference]::SilentlyContinue
$timeout = 300

function CheckTimeout {
    Param ([int]$count)
    If ($count -le 0) {
        Echo 'Script timed out. Aborting...' 
        Exit
    }
}   

Echo 'Waiting for OPC TOP Server to deploy...'
$countDown = $timeout
While (!(Test-Path C:\Users\topserver.ps1) -and ($countDown -gt 0)) {
	Start-Sleep -s 1
	$countDown --
}
Remove-Item C:\Users\topserver.ps1
Echo 'Done.'

Echo 'Waiting for MS SQL Server to Start...'
$countdown = $timeout
Do {
    $service = (Get-Service 'MSSQLSERVER').Status
    $countdown--
    Start-Sleep -s 1
} until ($service -eq 'Running' -or $countdown -eq 0)
CheckTimeout -count $countdown
Echo 'Done.'

Echo 'If historian is not HISTORIAN, delete HISTORIAN and add new historian - otherwise SMC eats all CPU later'
% if historian_name != "HISTORIAN":
$countDown = $timeout
Do {
    Start-Process -FilePath "C:\Program Files (x86)\Common Files\ArchestrA\aaSMC.exe"
    Show-Sleep(5)
    $countDown--
    $proc = Get-Process mmc -ErrorAction SilentlyContinue
} Until ($proc -or ($countDown -le 0))
CheckTimeout -count $countDown 
Echo "Done."

$countDown = $timeout
Do {
    $no = Get-UIAWindow -Name "Wonderware Historian Configuration Editor" | Get-UIAButton -n "No"
    $countDown--
} Until ($no -or ($countDown -le 0))
CheckTimeout -count $countDown
$no | Invoke-UIAButtonClick | Out-Null

Echo 'Remove old historian group HISTORIAN'
$countDown = $timeout
Do {
    $hist = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "HISTORIAN"
    $countDown--
} Until ($hist -or ($countDown -le 0))
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    $del = $hist[1] | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Delete*"
    $countDown--
} Until ($del -or ($countDown -le 0))
CheckTimeout -count $countDown
$del | Invoke-UIAMenuItemClick | Out-Null
Start-Sleep -s 5

$countDown = $timeout
Do{    
    $yes = Get-UIAWindow -Name "Delete Server" | Get-UIAButton -n "Yes"
    $countDown--
} Until ($yes -or ($countDown -le 0))
CheckTimeout -count $countDown 
$yes | Invoke-UIAButtonClick | Out-Null

Echo 'Add new historian group for ${historian_name}'
$countDown = $timeout
Do {
    $hist_group = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Historian Group"
    $hist_group | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "New Historian Registration..." | Invoke-UIAMenuItemClick | Out-Null
    $hist_name = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIAEdit -Name "Historian:" | Set-UIATextBoxText "${historian_name}"
    $domain = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIAEdit -Name "Domain:" | Set-UIATextBoxText "${historian_name}"
    $login = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIAEdit -Name "Login Name:" | Set-UIATextBoxText "wwuser"
    $pass = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIAEdit -Name "Password:" | Set-UIATextBoxText "Admin1!"
    $auth = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIARAdioButton -AutomationId '20412' -Name "Use Windows authentication" | Invoke-UIAControlClick | Out-Null
    $ok = Get-UIAWindow -Name "Registered Historian Properties" | Get-UIAButton -Name "OK"
    $countDown--
} Until ($ok -or ($countDown -le 0))
CheckTimeout -count $countDown 
$ok | Invoke-UIAButtonClick | Out-Null
Start-Sleep -s 5
Echo 'Done.'

Echo 'Close SMC...'
$countDown = $timeout
Do {
    $exit = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name "Close" 
} Until ($exit -or ($countDown -le 0))
CheckTimeout -count $countDown
$exit | Invoke-UIAButtonClick | Out-Null
%endif

Echo 'Open historian configuration wizard...'
$countDown = $timeout
Do {
    Start-Process -FilePath "C:\Program Files (x86)\Wonderware\Historian\aahDBDump.exe"
    Start-Sleep -s 1
    $countDown--
    $proc = Get-Process aahDBDump -ErrorAction SilentlyContinue
} Until ($proc -or ($countDown -le 0))
CheckTimeout -count $countDown 
Echo "Done."

Echo 'Import historian configuration...'
$countDown = $timeout
Do {
    $hist_ie = Get-UIAWindow -Name "Historian Database Export/Import Utility*" | Get-UIAButton -Name "Next >"
    Start-Sleep -s 1
    $countDown--
} Until ($hist_ie -or ($countdown -le 0))
CheckTimeout -count $countDown
$hist_ie | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    $file = Get-UIAWindow -Name "Historian Database Export/Import Utility*" | Get-UIAEdit -Name "File Name:" | Set-UIATextBoxText "C:\Users\wwuser\Documents\Configs\Inject\historian_config.txt"
    Start-Sleep -s 1 
    $countDown--
} Until ($file -or ($countdown -le 0))
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    $next1 = Get-UIAWindow -Name "Historian Database Export/Import Utility*" | Get-UIAButton -Name "Next >"
    Start-Sleep -s 1
    $countDown--
} Until ($next1 -or ($countdown -le 0))
CheckTimeout -count $countDown
$next1 | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    $next2 = Get-UIAWindow -Name "Historian Database Export/Import Utility*" | Get-UIAButton -Name "Next >"
    Show-Sleep(5)
    $countDown--
} Until ($next2 -or ($countdown -le 0))
CheckTimeout -count $countDown
$next2 | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    $finish = Get-UIAWindow -Name "Historian Database Export/Import Utility*" | Get-UIAButton -Name "Finish"
    Start-Sleep -s 1
    $countDown--
} Until ($finish -or ($countdown -le 0))
CheckTimeout -count $countDown
$finish | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'

Echo 'Opening System Management Console...'
$countDown = $timeout
Do {
    Start-Process -FilePath "C:\Program Files (x86)\Common Files\ArchestrA\aaSMC.exe"
    Show-Sleep(5)
    $countDown--
    $proc = Get-Process mmc -ErrorAction SilentlyContinue
} Until ($proc -or ($countDown -le 0))
CheckTimeout -count $countDown 
Echo 'Done.'

% if historian_name != "HISTORIAN":
Echo 'Add right historian name to IDAS'
$countDown = $timeout
Do {
    $hist_group = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "Historian Group" | Invoke-UIAControlClick -DoubleClick | Out-Null
    $hist_name = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "${historian_name}" | Invoke-UIAControlClick -DoubleClick | Out-Null
    $config_edit = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "Configuration Editor" | Invoke-UIAControlClick -DoubleClick | Out-Null
    $system_config = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "System Configuration" | Invoke-UIAControlClick -DoubleClick | Out-Null
    $data_acq = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "Data Acquisition" | Invoke-UIAControlClick -DoubleClick | Out-Null
    $idas = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "IDAS - historian" | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Properties" | Invoke-UIAMenuItemClick | Out-Null
    $modify = Get-UIAWindow -Name "IDAS - *" | Get-UIAButton -Name "Modify*" | Invoke-UIAButtonClick | Out-Null
    $yes =  Get-UIAButton -Name "Yes" | Invoke-UIAButtonClick | Out-Null
    $idas_name = Get-UIAWindow -Name "IDAS - *" | Get-UIAEdit -Name "IDAS Node*" | Set-UIATextBoxText "${historian_name}"
    $ok = Get-UIAWindow -Name "IDAS - *" |  Get-UIAButton -Name "OK" | Invoke-UIAButtonClick | Out-Null
    $conf = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Configuration Editor"
    $conf | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Commit Pending Changes..." | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $commit = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -n "Commit"
} Until ($commit -or ($countDown -le 0))
CheckTimeout -count $countDown
$commit | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    $commit = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -n "OK"
    Start-Sleep -s 1
    $countDown--
} Until ($commit -or ($countDown -le 0))
CheckTimeout -count $countDown
$commit | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'

Echo 'Opening Management Console'
$countDown = $timeout
Do {
    $mgmt_console = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -name "Management Console"
}Until ($mgmt_console -or ($countDown -le 0))
CheckTimeout -count $countDown
$mgmt_console | Invoke-UIAControlClick -DoubleClick | Out-Null

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $stat = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Status"
} Until ($stat -or ($countDown -le 0))
CheckTimeout -count $countDown 
$stat | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'
% endif

Echo 'Starting Historian...'
$countDown = $timeout
Do {
    $status = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Status"
    $status | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Start Historian" | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $ok = Get-UIAWindow -Name "Start Historian" | Get-UIAButton -n "OK"
} Until ($ok -or ($countDown -le 0))
CheckTimeout -count $countDown 
$ok | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'

% if hist_config.scadaConnectToHistorian:
#Give the historian time to startup prior to loading tags from SCADA for replication
Write-Host 'Wait for a bit as the Historian starts up...' -NoNewLine
$countDown = $timeout
Do {
    Start-Sleep -s 2
    $countDown--
    $serviceCount = (Get-Service "InSQL*" | Where-Object {$_.Status -eq "Stopped"}).count
    Write-Host "." -NoNewLine
    
} Until ((-not $serviceCount) -or ($countdown -le 0))
CheckTimeout -count $countDown
Show-Sleep(10)
Echo ''
Echo 'Done.'

    % for replication_ip in hist_config.replication_ips:
Echo 'Open Configuration Tree...'
$countDown = $timeout
Do {
    $replSrvr = Get-UIAWindow -Name "SMC -*" | Get-UIATreeItem -Name "Configuration Editor"
    $replSrvr | Invoke-UIATreeItemExpand | Out-Null
    $replSrvr = $replSrvr | Get-UIATreeItem -Name "System Configuration"
    $replSrvr | Invoke-UIATreeItemExpand | Out-Null
    $replSrvr = $replSrvr | Get-UIATreeItem -Name "Replication"
    $replSrvr | Invoke-UIATreeItemExpand | Out-Null
    $replSrvr = $replSrvr | Get-UIATreeItem -Name "Replication Servers"
    $replSrvr | Invoke-UIATreeItemExpand | Out-Null
    $replSrvr = $replSrvr | Get-UIATreeItem -Name "${replication_ip}"
    $replSrvr | Invoke-UIATreeItemExpand | Out-Null
    $replSrvr = $replSrvr | Get-UIATreeItem -Name "Simple Replication"
    $replSrvr | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Add Multiple Tags..." | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $countDown--
} Until ($replSrvr -or ($countdown -le 0))
CheckTimeout -count $countDown
Echo 'Done.'

Echo 'Add All Tags to Replication Server ${replication_ip}...'
$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $not1 = Get-UIAWindow -Name "SMC -*" | Get-UIACheckBox -AutomationId '204' -Name "Not" | Invoke-UIAControlClick
    
} Until ($not1 -or ($countdown -le 0))
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $name = Get-UIAWindow -Name "SMC -*" | Get-UIAEdit -Name "Tag Name: " | Set-UIATextBoxText "Sys"
} Until ($name -or ($countdown -le 0))
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $findnow = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name "Find Now"
    Start-Sleep -s 2
} Until ($findnow -or ($countdown -le 0))
$findnow | Invoke-UIAButtonClick | Out-Null
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $addall = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name ">>"
} Until ($addall -or ($countdown -le 0))
$addall | Invoke-UIAButtonClick | Out-Null
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $okbtn = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name "OK"
} Until ($okbtn -or ($countdown -le 0))
$okbtn | Invoke-UIAButtonClick | Out-Null
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $apply = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name "Apply"
} Until ($apply -or ($countdown -le 0))
$apply | Invoke-UIAButtonClick | Out-Null
CheckTimeout -count $countDown

$countDown = $timeout
Do {
    Start-Sleep -s 2
    $countDown--
    $close = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -Name "Close"
} Until ($close -or ($countdown -le 0))
$close | Invoke-UIAButtonClick | Out-Null
CheckTimeout -count $countDown
Echo 'Done.'
    % endfor

Echo 'Close Configuration Tree...'
$countDown = $timeout
Do {
    $replSrvr = Get-UIAWindow -Name "SMC -*" | Get-UIATreeItem -Name "Configuration Editor"
    $replSrvr | Invoke-UIATreeItemCollapse | Out-Null
    Start-Sleep -s 1
    $countDown--
} Until ($replSrvr -or ($countdown -le 0))
CheckTimeout -count $countDown
Echo 'Done.'

Echo 'Stop Historian...'
$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $stat = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Status" 
    $stat | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Stop Historian" | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $ok = Get-UIAWindow -Name "Stop Historian" | Get-UIAButton -n "OK"
} Until ($ok -or ($countDown -le 0))
CheckTimeout -count $countDown 
$ok | Invoke-UIAButtonClick | Out-Null

Show-Sleep(10)

Echo 'Committing pending changes...' 
$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $conf = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Configuration Editor"
    $conf | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Commit Pending Changes..." | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $commit = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -n "Commit"
} Until ($commit -or ($countDown -le 0))
CheckTimeout -count $countDown
$commit | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    $commit = Get-UIAWindow -Name "SMC -*" | Get-UIAButton -n "OK"
    Start-Sleep -s 1
    $countDown--
} Until ($commit -or ($countDown -le 0))
CheckTimeout -count $countDown
$commit | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'

Echo 'Restart Historian...'
$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $start = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Status" 
    $start | Invoke-UIAControlContextMenu | Get-UIAMenuItem -Name "Start Historian" | Invoke-UIAMenuItemClick | Out-Null
    Start-Sleep -s 1
    $restart = Get-UIAWindow -Name "Start Historian" | Get-UIAButton -n "OK"
} Until ($restart -or ($countDown -le 0))
CheckTimeout -count $countDown 
$restart | Invoke-UIAButtonClick | Out-Null

$countDown = $timeout
Do {
    Start-Sleep -s 1
    $countDown--
    $stat = Get-UIAWindow -Name "SMC -*" | Get-UIAControl -Name "Status"
} Until ($stat -or ($countDown -le 0))
CheckTimeout -count $countDown 
$stat | Invoke-UIAButtonClick | Out-Null
Echo 'Done.'

% endif

Echo 'Opening trends'
$countDown = $timeout
Do {
    Start-Process -FilePath "C:\Program Files (x86)\Wonderware\HistorianClient\aaTrend.exe"
    Start-Sleep -s 1
    $countDown--
    $proc = Get-Process aaTrend -ErrorAction SilentlyContinue
} Until ($proc -or ($countDown -le 0))
CheckTimeout -count $countDown 
Echo "Done."

#TODO Fix to check for success. Due to nested windows it always returned false even on success"
Echo 'Set server name'
Get-UIAWindow -Name "Trend*" | Get-UIAEdit -Name "Server:" | Set-UIATextBoxText "${historian_name}"
Start-Sleep -s 1
Get-UIAWindow -Name "Trend*" | Get-UIACheckBox -Name "Use Integrated security" | Invoke-UIAControlClick | Out-Null
Get-UIAWindow -Name "Trend*" | Get-UIAControl -Name "Add" | Invoke-UIAButtonClick | Out-Null
$close = Get-UIAWindow -Name "Trend*" | Get-UIAControl -Name "Close" 
$close[1] | Invoke-UIAButtonClick | Out-Null


Echo 'Removing Users share...'
net share Users /DELETE | Out-Null
Echo 'Done.'

Echo 'Removing UIA log...'
Remove-Item C:\Users\wwuser\Documents\UIA.log
Echo 'Done.'
