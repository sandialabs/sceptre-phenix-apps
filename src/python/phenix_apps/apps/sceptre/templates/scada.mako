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

while (-Not (Phenix-StartupComplete)) {
    Start-Sleep -s 30
}

$automation_filepath = "C:\myscada.exe"

if (Test-Path $automation_filepath) {
    # If the file exists, execute the command
    & $automation_filepath
} else {
    # If the file does not exist, use alternative automation
    Echo "opening myDESIGNER"
    # Open mydesigner
    Start-Process "C:\Program Files\myDESIGNER7\bin\mydesigner.exe" "--console new"

    Echo 'sleeping'
    # Wait for the mydesigner window to open
    Start-Sleep 90

    # Select "Import Project"
    $mydesigner = Select-Window -Active
    Start-Sleep 1
    $mydesigner | Send-Keys "{TAB}"
    Start-Sleep 1
    $mydesigner | Send-Keys "{TAB}"
    Start-Sleep 1
    $mydesigner | Send-Keys "{Enter}"
    Start-Sleep 1

    # Open "import.mep"
    Echo "opening autoproject"
    $select_win = Select-Window -Active
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{Enter}"
    Start-Sleep 1
    $select_win | Send-Keys "C:/Users/wwuser/Documents/Configs/Inject/"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{Enter}"
    Start-Sleep 1
    $select_win | Send-Keys "myscada.mep"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{Enter}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{TAB}"
    Start-Sleep 1
    $select_win | Send-Keys "{Enter}"
    Start-Sleep 10

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
}
