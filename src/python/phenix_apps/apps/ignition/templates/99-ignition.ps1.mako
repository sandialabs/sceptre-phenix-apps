## phenix igntion app
$ErrorActionPreference = 'Stop'

% if gwbk:
$staged = 'C:\phenix\ignition\restore.gwbk'
% else:
$staged = 'C:\phenix\ignition\devices'
% endif
% if perspective:
$stagedHmi = 'C:\phenix\ignition\perspective'

if (-not (Test-Path $staged) -and -not (Test-Path $stagedHmi)) {
% else:

if (-not (Test-Path $staged)) {
% endif
    Write-Output "[ignition] nothing staged; already configured."
    exit 0
}

Get-Service -Name Ignition | Out-Null

try {
    $deadline = (Get-Date).AddMinutes(2)
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
% if gwbk:
        $gwcmd = 'C:\Program Files\Inductive Automation\Ignition\gwcmd.bat'
        & $gwcmd -s $staged -m
        if ($LASTEXITCODE -ne 0) {
            throw "gwcmd failed restoring $staged (exit code $LASTEXITCODE)"
        }
        Remove-Item -Path $staged -Force
        Write-Output "[ignition] restored $staged"
% else:
        if (Test-Path $staged) {
            $target = 'C:\Program Files\Inductive Automation\Ignition\data\config\resources\core\com.inductiveautomation.opcua\device'
            New-Item -Path $target -ItemType Directory -Force | Out-Null
            Copy-Item -Path "$staged\*" -Destination $target -Recurse -Force
            Remove-Item -Path $staged -Recurse -Force
            Write-Output "[ignition] copied device resources into $target"
        }
% if perspective:

        if (Test-Path $stagedHmi) {
            $data = 'C:\Program Files\Inductive Automation\Ignition\data'

            $projDest = "$data\projects\${project}"
            if (Test-Path $projDest) {
                Remove-Item -Path $projDest -Recurse -Force
            }
            New-Item -Path "$data\projects" -ItemType Directory -Force | Out-Null
            Copy-Item -Path "$stagedHmi\project\${project}" -Destination $projDest -Recurse -Force

            $tagDest = "$data\config\resources\core\ignition\tag-definition\default"
            New-Item -Path $tagDest -ItemType Directory -Force | Out-Null
            Get-ChildItem -Path "$stagedHmi\tags" | ForEach-Object {
                $dest = Join-Path $tagDest $_.Name
                if (Test-Path $dest) {
                    Remove-Item -Path $dest -Recurse -Force
                }
                Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
            }

            Remove-Item -Path $stagedHmi -Recurse -Force
            Write-Output "[ignition] installed perspective project '${project}' and tags"
        }
% endif
% endif
    }
    finally {
        Start-Service -Name Ignition
    }
}
catch {
    Write-Error "[ignition] $_"
    exit 1
}

Write-Output "[ignition] configured!"
