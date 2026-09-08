Stop-ScheduledTask -TaskName "Adams'Drop" -ErrorAction SilentlyContinue
$target = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDrop.exe'))
Get-CimInstance Win32_Process -Filter "Name = 'AdamsDrop.exe'" | Where-Object { $_.ExecutablePath -eq $target } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
