## phenix ignition app (perspective client)

Write-Host "[ IGNITION ] Starting perspective viewer"
echo "[ IGNITION ] Starting perspective viewer"

$status = $null
while ($status -ne '200') {
    $status = curl.exe -s -o NUL -w '%{http_code}' '${url}'
    if ($status -ne '200') {
        Write-Host "[ IGNITION ] Gateway not ready yet, retrying in 10 seconds..."
        echo "[ IGNITION ] Gateway not ready yet, retrying in 10 seconds..."
        Start-Sleep -Seconds 10
    }
}

Write-Host "[ IGNITION ] Gateway ready, starting firefox"
echo "[ IGNITION ] Gateway ready, starting firefox"
Start-Process 'firefox.exe' '${url}'
Write-Host "[ IGNITION ] Gateway ready, firefox started, all done!"
echo "[ IGNITION ] Gateway ready, firefox started, all done!"
