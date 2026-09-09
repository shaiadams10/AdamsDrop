param([string]$Executable = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDrop.exe'))
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $Executable -WorkingDirectory (Split-Path -Parent $Executable)
$login = New-ScheduledTaskTrigger -AtLogOn -User $identity
$login.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Adams'Drop" -Action $action -Trigger $login -Principal $principal -Settings $settings -Force | Out-Null
Write-Output 'Optional login startup installed. No recovery loop or failure restart. Use start.ps1 to launch now.'
