param([string]$Executable = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist/AdamsDrop/AdamsDrop.exe'))
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $Executable -WorkingDirectory (Split-Path -Parent $Executable)
$login = New-ScheduledTaskTrigger -AtLogOn -User $identity
$login.Delay = 'PT5S'
$recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Adams'Drop" -Action $action -Trigger @($login,$recovery) -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Adams'Drop"
