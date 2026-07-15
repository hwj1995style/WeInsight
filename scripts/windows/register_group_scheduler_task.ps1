param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$TaskName = "WeInsight Group Scheduler",
    [string]$ConfigPath = "config\config.dev.yaml"
)

$ErrorActionPreference = "Stop"

$passwordValue = [Environment]::GetEnvironmentVariable("WEINSIGHT_MYSQL_PASSWORD", "User")
if ([string]::IsNullOrWhiteSpace($passwordValue)) {
    $passwordValue = [Environment]::GetEnvironmentVariable("WEINSIGHT_MYSQL_PASSWORD", "Machine")
}
if ([string]::IsNullOrWhiteSpace($passwordValue)) {
    throw "WEINSIGHT_MYSQL_PASSWORD must exist in User or Machine environment before registering the scheduled task."
}

$startScript = Join-Path $ProjectRoot "scripts\windows\start_group_scheduler.ps1"
if (-not (Test-Path $startScript)) {
    throw "Start script not found: $startScript"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -ProjectRoot `"$ProjectRoot`" -ConfigPath `"$ConfigPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs WeInsight group message scheduler in the interactive user session." `
    -Force | Out-Null

Write-Output "registered_task=$TaskName"
