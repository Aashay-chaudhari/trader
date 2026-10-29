# GUI-hosted anchor keeps WSL alive without owning the trading process.
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$stateDir = Join-Path $repo '.runtime'
[IO.Directory]::CreateDirectory($stateDir) | Out-Null
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = "$env:WINDIR\System32\wsl.exe"
$info.Arguments = '-d Ubuntu -u aasha -- /usr/bin/sleep infinity'
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$process = New-Object Diagnostics.Process
$process.StartInfo = $info
try {
    $null = $process.Start()
    @{ startedAt=[DateTimeOffset]::UtcNow.ToString('o'); hostPid=$PID; wslPid=$process.Id } | ConvertTo-Json -Compress | Set-Content (Join-Path $stateDir 'wsl-host.json')
    $process.WaitForExit()
    $code = $process.ExitCode
    @{ stoppedAt=[DateTimeOffset]::UtcNow.ToString('o'); exitCode=$code } | ConvertTo-Json -Compress | Add-Content (Join-Path $stateDir 'wsl-host.log')
    exit $code
} catch {
    @{ stoppedAt=[DateTimeOffset]::UtcNow.ToString('o'); errorType=$_.Exception.GetType().Name } | ConvertTo-Json -Compress | Add-Content (Join-Path $stateDir 'wsl-host.log')
    exit 1
} finally { $process.Dispose() }
