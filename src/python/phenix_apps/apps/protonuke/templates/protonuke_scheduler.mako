schtasks /create /tn "protonuke" /sc onlogon /rl highest /tr "C:\minimega\protonuke.exe ${protonuke_args}" /F
schtasks /run /tn "protonuke"
