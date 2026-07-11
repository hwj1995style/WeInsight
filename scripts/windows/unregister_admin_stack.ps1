$ErrorActionPreference = "Stop"

$taskNames = @(
    "WeInsight-Admin-Web",
    "WeInsight-Collector-Worker",
    "WeInsight-Pipeline-Worker"
)

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Output "unregistered_task=$taskName status=none"
        continue
    }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered_task=$taskName status=removed"
}
