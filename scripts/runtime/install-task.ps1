$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$stateDir = Join-Path $repo '.runtime'
[IO.Directory]::CreateDirectory($stateDir) | Out-Null
try {
    # Retire the visible-console owner. systemd owns the process from now on.
    $legacy = Get-ScheduledTask -TaskName 'AgentTrader-LocalSupervisor' -ErrorAction SilentlyContinue
    if ($legacy) {
        Disable-ScheduledTask -TaskName $legacy.TaskName | Out-Null
        Stop-ScheduledTask -TaskName $legacy.TaskName -ErrorAction SilentlyContinue
    }
    $hostTask = 'AgentTrader-WSLHost'
    $hiddenScript = Join-Path $PSScriptRoot 'hidden-launch.vbs'
    $hostAction = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument ('//B //NoLogo "' + $hiddenScript + '" host') -WorkingDirectory $repo
    $hostTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $hostSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
    $hostPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $hostTask -Action $hostAction -Trigger $hostTrigger -Settings $hostSettings -Principal $hostPrincipal -Description 'Hidden WSL keepalive anchor. systemd separately owns the trader service.' -Force | Out-Null
    Start-ScheduledTask -TaskName $hostTask
    $taskName = 'AgentTrader-IndependentWatchdog'
    $script = Join-Path $PSScriptRoot 'hidden-launch.vbs'
    $action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument ('//B //NoLogo "' + $script + '" watchdog') -WorkingDirectory $repo
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 2)
    $logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($repeat,$logon) -Settings $settings -Principal $principal -Description 'Hidden Windows watchdog. Checks independent heartbeat and systemd service every two minutes; recovers and alerts outside Python.' -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    @{ success=$true; task=$taskName; launcher='wscript hidden'; at=[DateTimeOffset]::UtcNow.ToString('o') } | ConvertTo-Json -Compress | Set-Content (Join-Path $stateDir 'watchdog-install.json')
} catch {
    @{ success=$false; errorType=$_.Exception.GetType().Name; at=[DateTimeOffset]::UtcNow.ToString('o') } | ConvertTo-Json -Compress | Set-Content (Join-Path $stateDir 'watchdog-install.json')
    exit 1
}
