Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinMin {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
foreach ($p in Get-Process etne -ErrorAction SilentlyContinue) {
    if ($p.MainWindowHandle -ne [IntPtr]::Zero) {
        [WinMin]::ShowWindow($p.MainWindowHandle, 6) | Out-Null
        Write-Output ("minimized " + $p.Id)
    }
}
