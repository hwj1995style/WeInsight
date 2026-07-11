param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ConfigPath = "config\config.prod.yaml",
    [string]$WebConfigPath = "",
    [string]$CollectorConfigPath = "",
    [string]$PipelineConfigPath = ""
)

$ErrorActionPreference = "Stop"

function Resolve-PersistedRequiredEnv {
    param([string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }
    $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }
    throw [System.InvalidOperationException]::new(
        "Missing required environment variable: $Name"
    )
}

function New-StackAction {
    param(
        [string]$PowerShellPath,
        [string]$StartScriptPath,
        [string]$ResolvedProjectRoot,
        [string]$ResolvedConfigPath
    )

    $argument = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -ProjectRoot "{1}" -ConfigPath "{2}"' -f (
        $StartScriptPath,
        $ResolvedProjectRoot,
        $ResolvedConfigPath
    )
    return New-ScheduledTaskAction `
        -Execute $PowerShellPath `
        -Argument $argument `
        -WorkingDirectory $ResolvedProjectRoot
}

function Resolve-StackConfigPath {
    param(
        [string]$RequestedPath,
        [string]$FallbackPath,
        [string]$ResolvedProjectRoot
    )

    $effectivePath = if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        $FallbackPath
    }
    else {
        $RequestedPath
    }
    $candidate = if ([IO.Path]::IsPathRooted($effectivePath)) {
        $effectivePath
    }
    else {
        Join-Path $ResolvedProjectRoot $effectivePath
    }
    $resolvedPath = (Resolve-Path -LiteralPath $candidate).Path
    if (-not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
        throw [System.IO.FileNotFoundException]::new("Config file is missing.")
    }
    $rootPrefix = $ResolvedProjectRoot.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPath.StartsWith(
        $rootPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw [System.UnauthorizedAccessException]::new(
            "ConfigPath must stay under ProjectRoot."
        )
    }
    return $resolvedPath
}

$legacyTaskNames = @(
    "WeInsight-Group-Scheduler",
    "WeInsight Group Scheduler"
)
foreach ($legacyTaskName in $legacyTaskNames) {
    $legacyTask = Get-ScheduledTask `
        -TaskName $legacyTaskName `
        -ErrorAction SilentlyContinue
    if ($null -ne $legacyTask) {
        throw [System.InvalidOperationException]::new(
            "Legacy scheduled task must be removed before registration: $legacyTaskName"
        )
    }
}

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedWebConfigPath = Resolve-StackConfigPath -RequestedPath $WebConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot
$resolvedCollectorConfigPath = Resolve-StackConfigPath -RequestedPath $CollectorConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot
$resolvedPipelineConfigPath = Resolve-StackConfigPath -RequestedPath $PipelineConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot

$adminWebScript = Join-Path $resolvedProjectRoot "scripts\windows\start_admin_web.ps1"
$collectorScript = Join-Path $resolvedProjectRoot "scripts\windows\start_collector_worker.ps1"
$pipelineScript = Join-Path $resolvedProjectRoot "scripts\windows\start_pipeline_worker.ps1"
foreach ($startScript in @($adminWebScript, $collectorScript, $pipelineScript)) {
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw [System.IO.FileNotFoundException]::new("Required start script is missing.")
    }
}

Resolve-PersistedRequiredEnv -Name "WEINSIGHT_WEB_MYSQL_PASSWORD" | Out-Null
Resolve-PersistedRequiredEnv -Name "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD" | Out-Null
Resolve-PersistedRequiredEnv -Name "WEINSIGHT_PIPELINE_MYSQL_PASSWORD" | Out-Null
Resolve-PersistedRequiredEnv -Name "WEINSIGHT_WEB_HOST" | Out-Null
Resolve-PersistedRequiredEnv -Name "WEINSIGHT_TLS_CERTFILE" | Out-Null
Resolve-PersistedRequiredEnv -Name "WEINSIGHT_TLS_KEYFILE" | Out-Null

$python = Get-Command python -CommandType Application -ErrorAction Stop
$powerShell = Get-Command powershell.exe -CommandType Application -ErrorAction Stop
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    throw [System.InvalidOperationException]::new(
        "Unable to resolve the current interactive Windows identity."
    )
}
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$adminWebAction = New-StackAction `
    -PowerShellPath $powerShell.Source `
    -StartScriptPath $adminWebScript `
    -ResolvedProjectRoot $resolvedProjectRoot `
    -ResolvedConfigPath $resolvedWebConfigPath
$collectorAction = New-StackAction `
    -PowerShellPath $powerShell.Source `
    -StartScriptPath $collectorScript `
    -ResolvedProjectRoot $resolvedProjectRoot `
    -ResolvedConfigPath $resolvedCollectorConfigPath
$pipelineAction = New-StackAction `
    -PowerShellPath $powerShell.Source `
    -StartScriptPath $pipelineScript `
    -ResolvedProjectRoot $resolvedProjectRoot `
    -ResolvedConfigPath $resolvedPipelineConfigPath

Register-ScheduledTask `
    -TaskName "WeInsight-Admin-Web" `
    -Action $adminWebAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs the WeInsight administration Web process." `
    -Force | Out-Null
Register-ScheduledTask `
    -TaskName "WeInsight-Collector-Worker" `
    -Action $collectorAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs the WeInsight collector in the interactive desktop session." `
    -Force | Out-Null
Register-ScheduledTask `
    -TaskName "WeInsight-Pipeline-Worker" `
    -Action $pipelineAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs the WeInsight non-UI pipeline process." `
    -Force | Out-Null

Write-Output "registered_task=WeInsight-Admin-Web"
Write-Output "registered_task=WeInsight-Collector-Worker"
Write-Output "registered_task=WeInsight-Pipeline-Worker"
