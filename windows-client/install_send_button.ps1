$ErrorActionPreference = 'Stop'
$taskExecutable = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDropSend.exe'
if (-not (Test-Path -LiteralPath $taskExecutable)) { throw 'Build AdamsDrop first.' }
$taskShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AdamsDrop - Send to iPad.lnk'
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
$taskShortcut.TargetPath = (Resolve-Path -LiteralPath $taskExecutable).Path
$taskShortcut.WorkingDirectory = Split-Path -Parent $taskExecutable
$taskShortcut.IconLocation = "$taskExecutable,0"
$taskShortcut.Description = 'Send selected Explorer files to iPad; otherwise choose files.'
$taskShortcut.Save()
Write-Output $taskShortcutPath
