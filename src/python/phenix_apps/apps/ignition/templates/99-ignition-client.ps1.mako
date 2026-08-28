## phenix ignition app (perspective client)
$ErrorActionPreference = 'Stop'

<%include file="perspective-open.ps1.mako" args="url=client_url"/>\

Write-Output "[ignition] configured!"
