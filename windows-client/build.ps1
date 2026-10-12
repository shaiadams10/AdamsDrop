$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path dist/AdamsDrop/config.json) { throw "Save the private config outside dist and stop/disable the task before rebuilding. See docs/WINDOWS.md." }
$iconPath = (Resolve-Path windows-client/tray_icon.ico).Path
python -m PyInstaller --noconfirm --windowed --onedir --name AdamsDrop --icon $iconPath --specpath build --paths windows-client --collect-all pymobiledevice3 --collect-all pmd_pytcp --collect-all pytun_pmd3 --copy-metadata pymobiledevice3 windows-client/receive_from_ipad.py

if ($LASTEXITCODE -ne 0) { throw 'Build failed' }

Copy-Item windows-client/ensure_apple_connection.ps1,windows-client/tray_icon.ico dist/AdamsDrop/
Copy-Item -LiteralPath dist/AdamsDrop/AdamsDrop.exe -Destination dist/AdamsDrop/AdamsDropSend.exe

Write-Output 'Built dist/AdamsDrop/AdamsDrop.exe. Copy config.example.json to config.json beside the executable and configure it.'
