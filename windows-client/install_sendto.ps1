$ErrorActionPreference = 'Stop'
$taskExecutable = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDrop.exe'
if (-not (Test-Path -LiteralPath $taskExecutable)) { throw 'Build AdamsDrop first.' }
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcutPath = Join-Path ([Environment]::GetFolderPath('SendTo')) 'AdamsDrop - iPad.lnk'
$taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
$taskShortcut.TargetPath = (Resolve-Path -LiteralPath $taskExecutable).Path
$taskShortcut.Arguments = '--send-files'
$taskShortcut.WorkingDirectory = Split-Path -Parent $taskExecutable
$taskShortcut.IconLocation = "$taskExecutable,0"
$taskShortcut.Save()
Write-Output 'Installed right-click > Send to > AdamsDrop - iPad (Windows 11: Show more options).'
