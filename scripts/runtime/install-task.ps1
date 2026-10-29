$ErrorActionPreference = 'Stop'
$taskName = 'AgentTrader-LocalSupervisor'
$repo = 'C:\Users\aasha\Desktop\trader'
$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wsl.exe" -Argument '-d Ubuntu -u aasha -- bash /mnt/c/Users/aasha/Desktop/trader/scripts/runtime/launch.sh' -WorkingDirectory $repo
$morning = New-ScheduledTaskTrigger -Daily -At '7:40AM'
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero)
# S4U does not expose interactive-user WSL distribution/authentication reliably.
# Interactive logon works with a locked desktop; sign in after a Windows reboot.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($morning,$logon) -Settings $settings -Principal $principal -Description 'Local paper trading supervisor. Research 08:15 Eastern; deterministic risk and close; sanitized GitHub Pages snapshots.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
