schtasks.exe /create /sc onstart /rl highest /tn sceptre-startup /tr "powershell.exe -ep bypass C:\sceptre\sceptre-startup.ps1 > C:\sceptre\sceptre-startup.log" /f
schtasks.exe /run /tn "sceptre-startup"
