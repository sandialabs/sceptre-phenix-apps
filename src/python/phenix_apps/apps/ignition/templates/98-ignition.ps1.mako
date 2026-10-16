## phenix ignition app (gwbk restore)
$ErrorActionPreference = 'Stop'

Write-Host "[ IGNITION ] Configuring static .gwbk"
echo "[ IGNITION ] Configuring static .gwbk"

$staged = 'C:\phenix\ignition\restore.gwbk'

if (-not (Test-Path $staged)) {
    Write-Host "[ IGNITION ] nothing staged; already configured."
    echo "[ IGNITION ] nothing staged; already configured."
    exit 0
}

Get-Service -Name Ignition | Out-Null

try {
    $deadline = (Get-Date).AddMinutes(5)
    while ($true) {
        try {
            Stop-Service -Name Ignition -Force
            break
        }
        catch {
            if ((Get-Date) -ge $deadline) { throw }
            Start-Sleep -Seconds 2
        }
    }

    try {
        $gwcmd = 'C:\Program Files\Inductive Automation\Ignition\gwcmd.bat'
        & $gwcmd -s $staged -m
        if ($LASTEXITCODE -ne 0) {
            throw "gwcmd failed restoring $staged (exit code $LASTEXITCODE)"
        }
        Remove-Item -Path $staged -Force
        Write-Host "[ IGNITION ] restored $staged"
        echo "[ IGNITION ] restored $staged"
    }
    finally {
        Start-Service -Name Ignition
    }
}
catch {
    Write-Error "[ IGNITION ] $_"
    echo "[ IGNITION ] $_"
    exit 1
}

Write-Host "[ IGNITION ] configured!"
echo "[ IGNITION ] configured!"
