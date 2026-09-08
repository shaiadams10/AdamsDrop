& "$PSScriptRoot/stop.ps1"
Unregister-ScheduledTask -TaskName "Adams'Drop" -Confirm:$false -ErrorAction SilentlyContinue
