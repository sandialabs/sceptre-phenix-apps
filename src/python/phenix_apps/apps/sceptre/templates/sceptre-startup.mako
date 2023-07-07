Get-ChildItem '/sceptre/startup/*.ps1' | ForEach-Object {
    & $_.FullName
}
