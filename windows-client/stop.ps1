Stop-ScheduledTask -TaskName "Adams'Drop" -ErrorAction SilentlyContinue
$target = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDrop.exe'))
$sendTarget = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDropSend.exe'))
Get-CimInstance Win32_Process -Filter "Name = 'AdamsDrop.exe' OR Name = 'AdamsDropSend.exe'" | Where-Object { $_.ExecutablePath -in @($target, $sendTarget) } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
