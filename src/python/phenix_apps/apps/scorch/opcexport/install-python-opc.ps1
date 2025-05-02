Echo 'Setting up Python...'

Echo "PATH: $env:path"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") 
Echo "PATH (POST-SET FROM SYSTEM): $env:path"

if ((Get-Command 'python.exe' -ErrorAction SilentlyContinue) -eq $null) {
    Echo 'Installing Python...'
    # https://docs.python.org/3/using/windows.html#installing-without-ui
    # TODO: do we need to run as Administrator? "-Verb RunAs" when invoking this install script
    Start-Process -FilePath 'C:\opcexport\python-3.8.9-amd64.exe' -Wait -NoNewWindow -ArgumentList '/quiet', 'PrependPath=1', 'InstallAllUsers=1', 'Include_test=0', 'Include_tcltk=0', 'Include_doc=0'
} else {
    Echo 'Python is already installed'
}

Echo "PATH: $env:path"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") 
Echo "PATH (POST-SET FROM SYSTEM): $env:path"

if (-not(Test-Path -Path 'C:\opcexport\pip_package_download')) {
    Echo 'Extracting pip packages...'
    # NOTE: the PowerShell version on opc.qc2 is too old for 'Expand-Archive'...however, it DOES have 7-zip!
    if ((Get-Command Expand-Archive -ErrorAction SilentlyContinue) -eq $null) {
        & ${env:ProgramFiles}\7-Zip\7z.exe x 'C:\opcexport\opc_pip_packages.zip' '-oC:\opcexport\' -y
    } else {
        Expand-Archive -Path 'C:\opcexport\opc_pip_packages.zip' -DestinationPath 'C:\opcexport\' -Force
    }
    
    if (Get-Command 'python.exe' -ErrorAction SilentlyContinue) {
        $pyPath = (Get-Command 'python.exe' -ErrorAction SilentlyContinue).Definition
    } else {
        $pyPath = 'C:\Progra~1\Python38\python.exe'
    }
    Echo "Python path: $pyPath"
    $env:path += ";$pyPath"
    Echo "Updated PATH: $env:path"

    # TODO: why sleep? wait until 7z is done?
    Echo 'Sleeping for 60 seconds...'
    Start-Sleep -Seconds 60

    $files = Get-ChildItem 'C:\opcexport\pip_package_download' -Filter *.whl
    foreach ($file in $files) {
        Echo 'Installing package $file'
        & $pyPath -m pip install --progress-bar off --no-input --no-index --find-links C:\opcexport\pip_package_download C:\opcexport\pip_package_download\$file
    }
} else {
    Echo 'pip packages are already installed'
}

Echo 'Finished setting up Python'
