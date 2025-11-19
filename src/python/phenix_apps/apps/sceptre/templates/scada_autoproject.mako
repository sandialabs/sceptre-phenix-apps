Import-Module Wasp
Import-Module C:\Windows\System32\UIAutomation.0.8.7B3.NET35\UIAutomation.dll

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

$timeout = 300
function CheckTimeout {
    Param ([int]$count)
    If ($count -le 0) {
    	Echo 'Script timed out. Aborting...'
	Exit
    }
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public class Mouse
{
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);

    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    private const uint MOUSEEVENTF_RIGHTUP = 0x0010;

    public static void LeftClick(int x, int y)
    {
        SetCursorPos(x, y);
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
    }

    public static void RightClick(int x, int y)
    {
        SetCursorPos(x, y);
        mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, UIntPtr.Zero);
        mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, UIntPtr.Zero);
    }
}
"@


Echo "opening myDESIGNER"
# Open mydesigner
Start-Process "C:\Program Files\myDESIGNER7\bin\mydesigner.exe" "--console new"

Echo 'sleeping'
#  Hack - wait for the mydesigner window to open
# TODO - will put a real check in here once things are working
Start-Sleep 90

# Select "Existing Project"
$mydesigner = Select-Window -Active
Start-Sleep 1
$mydesigner | Send-Keys "{TAB}"
Start-Sleep 1
$mydesigner | Send-Keys "{TAB}"
Start-Sleep 1
$mydesigner | Send-Keys "{TAB}"
Start-Sleep 1
$mydesigner | Send-Keys "{TAB}"
Start-Sleep 1
$mydesigner | Send-Keys "{Enter}"
Start-Sleep 1

# Open "autoproject"
Echo "opening autoproject"
$select_win = Select-Window -Active
Start-Sleep 1
$select_win | Send-Keys "autoproject"
Start-Sleep 1
$select_win | Send-Keys "{Enter}"
Start-Sleep 1

# Select "Download to Devices" button using menus
$select_win = Select-Window -Active
Start-Sleep 1
$select_win | Send-Keys "{F10}"
Start-Sleep 1
$select_win | Send-Keys "{RIGHT}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{RIGHT}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{DOWN}"
Start-Sleep 1
$select_win | Send-Keys "{ENTER}"
Start-Sleep 1

# Checkbox for "This Computer"  
# This is a hack...the checkbox is not accessible through any keyboard commands :(
Echo "Hitting download"
Start-Sleep 1
#the real hack
[Mouse]::LeftClick(28, 122)

# Hit "Download to Devices" button
$select_win = Select-Window -Active
Start-Sleep 1
$select_win | Send-Keys "+{TAB}" #we get stuck in the pane so we need to SHFT-TAB instead of just TAB
Start-Sleep 1
$select_win | Send-Keys "+{TAB}"
Start-Sleep 1
$select_win | Send-Keys "+{TAB}"
Start-Sleep 1
$select_win | Send-Keys "+{TAB}"
Start-Sleep 1
$select_win | Send-Keys "{ENTER}"

# Wait for stuff to load
Start-Sleep 30

# Hit "Download to Devices" button
Start-Sleep 1
$select_win | Send-Keys "{TAB}"
Start-Sleep 1
$select_win | Send-Keys "{TAB}"
Start-Sleep 1
$select_win | Send-Keys "{ENTER}"

# Hit "Yes" button
Start-Sleep 10
$select_win | Send-Keys "{ENTER}"

# Hit "Ok" button
Start-Sleep 10
$select_win | Send-Keys "{ENTER}"








#C:\myscada.exe

