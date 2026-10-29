# Runs on Windows independently of the Python process and the WSL console.
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$stateDir = Join-Path $repo '.runtime'
[IO.Directory]::CreateDirectory($stateDir) | Out-Null
$mutex = New-Object Threading.Mutex($false, 'Local\AgentTraderWatchdog')
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { $mutex.Dispose(); exit 0 }
$watchState = @{ incident = $false; lastAlert = ''; lastRestart = '' }
$stateFile = Join-Path $stateDir 'watchdog-state.json'
try { if (Test-Path $stateFile) { $old = Get-Content $stateFile -Raw | ConvertFrom-Json; foreach ($key in @('incident','lastAlert','lastRestart')) { if ($null -ne $old.$key) { $watchState[$key] = $old.$key } } } } catch {}

function Write-Record($kind, $detail) {
    $record = @{ at = [DateTimeOffset]::UtcNow.ToString('o'); kind = $kind; detail = $detail }
    [IO.File]::AppendAllText((Join-Path $stateDir 'watchdog.log'), (($record | ConvertTo-Json -Compress -Depth 4) + [Environment]::NewLine))
}
function Send-Alert($title, $body) {
    # Read only the notification destination. Never evaluate .env as code or log it.
    $topic = $null
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $repo '.env'))) {
        if ($line -match '^\s*NTFY_TOPIC\s*=\s*(.*?)\s*$') { $topic = $Matches[1].Trim().Trim('"').Trim("'"); break }
    }
    if (-not $topic -or $topic -notmatch '^[A-Za-z0-9_-]+$') { Write-Record 'notification_failed' 'Missing or invalid local notification topic'; return }
    try {
        $text = $body + "`nhttps://aashay-chaudhari.github.io/trader/"
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri ('https://ntfy.sh/' + $topic) -Body ([Text.Encoding]::UTF8.GetBytes($text)) -Headers @{ Title=$title; Priority='high'; Tags='warning' } -TimeoutSec 12 | Out-Null
        Write-Record 'notification_sent' $title
    } catch { Write-Record 'notification_failed' ($_.Exception.GetType().Name) }
}
function Invoke-ServiceCommand($operation) {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = "$env:WINDIR\System32\wsl.exe"
    # Fixed operations only; no shell interpolation and no user-derived arguments.
    switch ($operation) {
        'status' { $arguments = '-d Ubuntu -u aasha -- systemctl --user is-active agent-trader.service' }
        'start' { $arguments = '-d Ubuntu -u aasha -- systemctl --user start agent-trader.service' }
        'restart' { $arguments = '-d Ubuntu -u aasha -- systemctl --user restart agent-trader.service' }
        default { throw 'Unsupported service operation' }
    }
    $startInfo.Arguments = $arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    if (-not $process.WaitForExit(25000)) {
        try { $process.Kill() } catch {}
        $process.Dispose()
        throw 'WSL service command timed out'
    }
    $output = $process.StandardOutput.ReadToEnd().Trim()
    $code = $process.ExitCode
    $process.Dispose()
    return @{ output=$output; code=$code }
}
try {
    if (Test-Path (Join-Path $stateDir 'maintenance.flag')) { Write-Record 'maintenance_pause' 'Recovery intentionally paused by local operator'; exit 0 }
    $now = [DateTimeOffset]::UtcNow
    $heartbeat = $null
    try { $heartbeat = Get-Content (Join-Path $stateDir 'heartbeat.json') -Raw | ConvertFrom-Json } catch {}
    $age = [double]::PositiveInfinity
    if ($heartbeat) { try { $age = ($now - [DateTimeOffset]::Parse($heartbeat.at)).TotalSeconds } catch {} }
    $hostTask = Get-ScheduledTask -TaskName 'AgentTrader-WSLHost'
    if ($hostTask.State.ToString() -ne 'Running') {
        Start-ScheduledTask -TaskName 'AgentTrader-WSLHost'
        Write-Record 'host_restarted' 'Hidden WSL keepalive anchor restarted'
    }
    $service = Invoke-ServiceCommand 'status'
    $active = $service.code -eq 0 -and $service.output -eq 'active'
    $fresh = $age -ge -120 -and $age -le 180
    if (-not $active -or -not $fresh) {
        $reason = if (-not $active) { 'Background service is not active' } else { 'Heartbeat is missing or older than three minutes' }
        $canAlert = -not $watchState.lastAlert -or ($now - [DateTimeOffset]::Parse($watchState.lastAlert)).TotalMinutes -ge 15
        if (-not $watchState.incident -or $canAlert) { Send-Alert 'Trader - independent watchdog' ($reason + '. Attempting recovery.'); $watchState.lastAlert = $now.ToString('o') }
        $watchState.incident = $true
        $cooldown = $active -and $watchState.lastRestart -and ($now - [DateTimeOffset]::Parse($watchState.lastRestart)).TotalSeconds -lt 180
        if (-not $cooldown) {
            $operation = if ($active) { 'restart' } else { 'start' }
            $watchState.lastRestart = $now.ToString('o')
            $result = Invoke-ServiceCommand $operation
            Write-Record 'recovery_attempt' @{ operation=$operation; exitCode=$result.code; reason=$reason }
            if ($result.code -ne 0) { throw 'Service recovery command failed' }
        }
    } elseif ($watchState.incident) {
        Send-Alert 'Trader - watchdog recovery confirmed' 'The background service is active and its heartbeat is fresh again.'
        $watchState.incident = $false
        Write-Record 'recovery_confirmed' @{ heartbeatAgeSeconds=[math]::Round($age); service='active' }
    } else {
        Write-Record 'healthy' @{ heartbeatAgeSeconds=[math]::Round($age); service='active' }
    }
} catch {
    $now = [DateTimeOffset]::UtcNow
    Write-Record 'watchdog_error' ($_.Exception.GetType().Name)
    if (-not $watchState.lastAlert -or ($now - [DateTimeOffset]::Parse($watchState.lastAlert)).TotalMinutes -ge 15) {
        Send-Alert 'Trader - watchdog needs attention' 'Windows cannot confirm or recover the local background service. Check the PC and local watchdog log.'
        $watchState.lastAlert = $now.ToString('o')
    }
    $watchState.incident = $true
} finally {
    $watchState['checkedAt'] = [DateTimeOffset]::UtcNow.ToString('o')
    $temp = $stateFile + '.' + $PID + '.tmp'
    [IO.File]::WriteAllText($temp, ($watchState | ConvertTo-Json -Compress))
    Move-Item -Force -LiteralPath $temp -Destination $stateFile
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
