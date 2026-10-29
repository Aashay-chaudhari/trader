$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
trap { @{ error=$_.Exception.Message;at=[DateTimeOffset]::UtcNow.ToString('o') } | ConvertTo-Json -Compress | Set-Content (Join-Path $repo '.runtime\windows-inspection.json'); exit 1 }
$tasks = @('AgentTrader-LocalSupervisor','AgentTrader-WSLHost','AgentTrader-IndependentWatchdog') | ForEach-Object {
    $t = Get-ScheduledTask -TaskName $_
    $i = Get-ScheduledTaskInfo -TaskName $_
    @{ name=$t.TaskName; state=$t.State.ToString(); result=$i.LastTaskResult; lastRun=[string]$i.LastRunTime; nextRun=[string]$i.NextRunTime; executable=($t.Actions.Execute -join ';'); arguments=($t.Actions.Arguments -join ';'); limit=$t.Settings.ExecutionTimeLimit; repetition=$t.Triggers.Repetition.Interval }
}
$scriptErrors = @()
foreach ($file in Get-ChildItem $PSScriptRoot -Filter '*.ps1') {
    $parseErrors=$null; $tokens=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$parseErrors)
    foreach($e in $parseErrors) { $scriptErrors += @{file=$file.Name;line=$e.Extent.StartLineNumber;message=$e.Message} }
}
@{ checkedAt=[DateTimeOffset]::UtcNow.ToString('o');tasks=$tasks;parseErrors=$scriptErrors } | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $repo '.runtime\windows-inspection.json')
