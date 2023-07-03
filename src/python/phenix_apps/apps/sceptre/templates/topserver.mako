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


# Waiting for startup.ps1 to finish
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

%if primary_opc==False:
Echo 'Not the primary OPC so waiting for primary to start up'
Start-Sleep -s 360
%endif

Echo ''
Echo 'Configuring OPC server...'

$ErrorActionPreference = [System.Management.Automation.ActionPreference]::SilentlyContinue

$timeout = 300
function CheckTimeout {
	Param ([int]$count)
	If ($count -le 0) {
		Echo 'Script timed out. Aborting...'
		Exit
	}
}

$needs_restart = $True #while true, the OPC service needs to be restarted
While ($True) {
    Echo 'Opening TOP Server...'
    $countDown = $timeout

    # Open the TOP Server configuration software
    Do {
        Start-Process -FilePath "C:\Program Files (x86)\Software Toolbox\TOP Server 5\server_config.exe"
        Start-Sleep -s 1
        $countDown--
        $proc = Get-Process server_config -ErrorAction SilentlyContinue
    } Until ($proc -or ($countDown -le 0))
    CheckTimeout -count $countDown
    $countDown = $timeout

    # Verify the TOP server configuration window is open
    Do {
        Start-Sleep -s 1
        $countDown--
        $top = Select-Window server_config
    } Until (($top.ProcessName -eq "server_config") -or ($countDown -le -0))
    CheckTimeout -count $countDown
    Echo 'Done.'

    if ($needs_restart) {
        Echo 'Loading in injected configuration file...'
        $countDown = $timeout

        # Open injected OPC configuration file
        Do {
            Start-Sleep -s 1
            $countDown--
            $top | Send-Keys '^{o}'
            $open_win = Get-UIAWindow -Name "Open"
        } Until ($open_win -or ($countDown -le 0))
        CheckTimeout -count $countDown
        $countDown = $timeout
        Do {
            Start-Sleep -s 1
            $countDown--
            $textboxes = $open_win | Get-UIATextBox
        } Until ($textboxes -or ($countDown -le 0))
        CheckTimeout -count $countDown
        $textboxes[4] | Set-UIATextBoxText -Text "C:\Users\wwuser\Documents\Configs\Inject\opc.xml" | Out-Null
        $countDown = $timeout
        Do {
            Start-Sleep -s 1
            $countDown--
            $open = $open_win | Get-UIAButton -n "Open" 
        } Until ($open -or ($countDown -le 0))
        CheckTimeout -count $countDown
        $open | Invoke-UIAButtonClick | Out-Null
        $countDown = $timeout
        Do {
            Start-Sleep -s 1
            $countDown--
            $dial = Get-UIAWindow -Name "TOP Server" | Get-UIAButton -n "Yes, Update"
        } Until ($dial -or ($countDown -le 0))
        CheckTimeout -count $countDown
        $dial | Invoke-UIAButtonClick | Out-Null
        Echo "Done."
        Echo 'Restarting TOP Server...'
        Start-Sleep -s 2
        Stop-Process -Name server_config
        Show-Sleep(5)
        Restart-Service TOPServerV5
        Show-Sleep(5)
        $needs_restart = $False
    } Else {
        Break
    }
}

# Recheck to make sure the TOPServer configuration software opens
Do {
    Start-Sleep -s 1
    $countDown--
    $top = Select-Window server_config
} Until (($top.ProcessName -eq "server_config") -or ($countDown -le -0))

# Open up the Quick Client software to initialize all configured channels
Start-Sleep -s 5
$top | Send-Keys '%'
Start-Sleep -s 0.5
$top | Send-Keys '{RIGHT}' 
Start-Sleep -s 0.5
$top | Send-Keys '{RIGHT}' 
Start-Sleep -s 0.5
$top | Send-Keys '{RIGHT}' 
Start-Sleep -s 0.5
$top | Send-Keys '{DOWN}' 
Start-Sleep -s 0.5
$top | Send-Keys '{DOWN}' 
Start-Sleep -s 0.5
$top | Send-Keys '{ENTER}' 

# Verify the Quick Client opens
Do {
    Start-Sleep -s 1
    $countDown--
    $qc = Select-Window opcquickclient
} Until (($qc.ProcessName -eq "opcquickclient") -or ($countDown -le -0))
Start-Sleep -s 10

Echo 'Informing SCADA server that TOP Server configuration is complete...'
% for scada_addr in scada_ips:
% if scada_addr.split('.')[:-1] == opc_ip.split('.')[:-1]:
Copy-Item -Path C:\topserver.ps1 -Destination \\${scada_addr}\Users -Force
% endif
% endfor
Echo 'Done.'

Echo 'Informing Historians that TOP Server configuration is complete...'
% for historian_addr in historian_ips:
% if historian_addr.split('.')[:-1] == opc_ip.split('.')[:-1]:
Copy-Item -Path C:\topserver.ps1 -Destination \\${historian_addr}\Users -Force
% endif
% endfor
Echo 'Done.'

Echo 'Removing Users share...'
net share Users /DELETE | Out-Null
Echo 'Done.'

Echo 'Removing UIA log...'
Remove-Item C:\Users\wwuser\Documents\UIA.log
Echo 'Done.'
