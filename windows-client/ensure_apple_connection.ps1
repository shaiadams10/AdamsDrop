# Start Apple's packaged connection helper only if usbmux is unavailable.
$ErrorActionPreference = 'Stop'
$probe = [System.Net.Sockets.TcpClient]::new()
try {
    $connect = $probe.ConnectAsync('127.0.0.1', 27015)
    if ($connect.Wait(500) -and $probe.Connected) { exit 0 }
} catch {} finally { $probe.Dispose() }
$package = Get-AppxPackage -Name AppleInc.AppleDevices | Select-Object -First 1
if (-not $package) { exit 1 }
$launcher = Join-Path $package.InstallLocation 'AppleMobileDeviceLauncher.exe'
if (-not (Test-Path -LiteralPath $launcher)) { exit 1 }
Start-Process -FilePath $launcher -WindowStyle Hidden
