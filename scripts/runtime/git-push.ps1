# Noninteractive publication fallback; never allocate a Windows console.
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = 'C:\Program Files\Git\cmd\git.exe'
$info.Arguments = 'push origin HEAD:main'
$info.WorkingDirectory = $repo
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$info.EnvironmentVariables['GCM_INTERACTIVE'] = 'Never'
$info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
$process = New-Object Diagnostics.Process
$process.StartInfo = $info
$code = 1
try {
    $null = $process.Start()
    if (-not $process.WaitForExit(75000)) { try {$process.Kill()} catch {}; throw 'Git push timed out' }
    $code = $process.ExitCode
} catch { $code = 1 }
finally {
    @{at=[DateTimeOffset]::UtcNow.ToString('o');exitCode=$code} | ConvertTo-Json -Compress | Set-Content (Join-Path $repo '.runtime\windows-git-push.json')
    $process.Dispose()
}
exit $code
