param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ConfigPath = "config\config.prod.yaml",
    [string]$WebConfigPath = "",
    [string]$CollectorConfigPath = "",
    [string]$PipelineConfigPath = ""
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredEnv {
    param([string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }
    $value = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        [Environment]::SetEnvironmentVariable($Name, $value, "Process")
        return $value
    }
    $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        [Environment]::SetEnvironmentVariable($Name, $value, "Process")
        return $value
    }
    throw [System.InvalidOperationException]::new(
        "Missing required environment variable: $Name"
    )
}

function Set-RoleMysqlPassword {
    param([string]$RoleEnvironmentName)

    $mysqlPassword = Resolve-RequiredEnv -Name $RoleEnvironmentName
    [Environment]::SetEnvironmentVariable("WEINSIGHT_MYSQL_PASSWORD", $mysqlPassword, "Process")
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

function Get-TaskStatusSafe {
    param([string]$TaskName)

    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            return "not_found"
        }
        return $task.State.ToString().ToLowerInvariant()
    }
    catch {
        return "unknown"
    }
}

function Get-LegacyTaskPresenceSafe {
    $legacyNames = @(
        "WeInsight-Group-Scheduler",
        "WeInsight Group Scheduler"
    )
    try {
        foreach ($legacyName in $legacyNames) {
            $task = Get-ScheduledTask `
                -TaskName $legacyName `
                -ErrorAction SilentlyContinue
            if ($null -ne $task) {
                return "true"
            }
        }
        return "false"
    }
    catch {
        return "unknown"
    }
}

function Resolve-PrivateWebAddress {
    param([string]$HostName)

    if (
        [string]::IsNullOrWhiteSpace($HostName) -or
        $HostName -ne $HostName.Trim()
    ) {
        throw [System.ArgumentException]::new("Web host must be a private IP.")
    }
    $address = $null
    if (-not [Net.IPAddress]::TryParse($HostName, [ref]$address)) {
        throw [System.ArgumentException]::new("Web host must be a private IP.")
    }
    $bytes = $address.GetAddressBytes()
    $isPrivate = $false
    if ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) {
        if ($address.ToString() -ne $HostName) {
            throw [System.ArgumentException]::new("Web host must be a private IP.")
        }
        $isPrivate = (
            $bytes[0] -eq 10 -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
        )
    }
    elseif ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetworkV6) {
        $isPrivate = (($bytes[0] -band 0xFE) -eq 0xFC)
    }
    if (-not $isPrivate) {
        throw [System.ArgumentException]::new("Web host must be a private IP.")
    }
    return $address
}

$runtimeReady = $false
$resolvedProjectRoot = $null
$resolvedWebConfigPath = $null
$resolvedCollectorConfigPath = $null
$resolvedPipelineConfigPath = $null
$python = $null
try {
    $resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $mainModulePath = Join-Path $resolvedProjectRoot "app\main.py"
    if (-not (Test-Path -LiteralPath $mainModulePath -PathType Leaf)) {
        throw [System.IO.FileNotFoundException]::new("Main module is missing.")
    }
    $python = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    $runtimeReady = $true
}
catch {
    $runtimeReady = $false
}

if ($runtimeReady) {
    try {
        $resolvedWebConfigPath = Resolve-StackConfigPath -RequestedPath $WebConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot
    }
    catch {
        $resolvedWebConfigPath = $null
    }
    try {
        $resolvedCollectorConfigPath = Resolve-StackConfigPath -RequestedPath $CollectorConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot
    }
    catch {
        $resolvedCollectorConfigPath = $null
    }
    try {
        $resolvedPipelineConfigPath = Resolve-StackConfigPath -RequestedPath $PipelineConfigPath -FallbackPath $ConfigPath -ResolvedProjectRoot $resolvedProjectRoot
    }
    catch {
        $resolvedPipelineConfigPath = $null
    }
}

$webTaskStatus = Get-TaskStatusSafe -TaskName "WeInsight-Admin-Web"
$collectorTaskStatus = Get-TaskStatusSafe -TaskName "WeInsight-Collector-Worker"
$pipelineTaskStatus = Get-TaskStatusSafe -TaskName "WeInsight-Pipeline-Worker"
$legacyTaskPresent = Get-LegacyTaskPresenceSafe

$webHttpsReachable = "unreachable"
try {
    $webHost = Resolve-RequiredEnv -Name "WEINSIGHT_WEB_HOST"
    $webAddress = Resolve-PrivateWebAddress -HostName $webHost
    $uriHost = if (
        $webAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetworkV6
    ) {
        "[{0}]" -f $webAddress.ToString()
    }
    else {
        $webAddress.ToString()
    }
    $webPort = 8848
    $webUri = "https://{0}:{1}/" -f $uriHost, $webPort
    $response = Invoke-WebRequest `
        -Uri $webUri `
        -UseBasicParsing `
        -TimeoutSec 5 `
        -Method Get
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        $webHttpsReachable = "reachable"
    }
}
catch {
    $webHttpsReachable = "unreachable"
}

$configChecks = @(
    @{
        RoleEnvironmentName = "WEINSIGHT_WEB_MYSQL_PASSWORD"
        ConfigPath = $resolvedWebConfigPath
    },
    @{
        RoleEnvironmentName = "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD"
        ConfigPath = $resolvedCollectorConfigPath
    },
    @{
        RoleEnvironmentName = "WEINSIGHT_PIPELINE_MYSQL_PASSWORD"
        ConfigPath = $resolvedPipelineConfigPath
    }
)
$allConfigChecksSucceeded = $true
if (-not $runtimeReady) {
    $allConfigChecksSucceeded = $false
}
else {
    $locationPushed = $false
    try {
        Push-Location -LiteralPath $resolvedProjectRoot
        $locationPushed = $true
        foreach ($configCheck in $configChecks) {
            if ($null -eq $configCheck.ConfigPath) {
                $allConfigChecksSucceeded = $false
                continue
            }
            try {
                Set-RoleMysqlPassword `
                    -RoleEnvironmentName $configCheck.RoleEnvironmentName
                Resolve-RequiredEnv -Name "WEINSIGHT_WEB_HOST" | Out-Null
                Resolve-RequiredEnv -Name "WEINSIGHT_TLS_CERTFILE" | Out-Null
                Resolve-RequiredEnv -Name "WEINSIGHT_TLS_KEYFILE" | Out-Null
                $configArguments = @("-m", "app.main", "check-config", "--config", $configCheck.ConfigPath)
                & $python @configArguments *> $null
                if ($LASTEXITCODE -ne 0) {
                    $allConfigChecksSucceeded = $false
                }
            }
            catch {
                $allConfigChecksSucceeded = $false
            }
        }
    }
    catch {
        $allConfigChecksSucceeded = $false
    }
    finally {
        if ($locationPushed) {
            Pop-Location
        }
    }
}
$mysqlConfigOk = if ($allConfigChecksSucceeded) {
    "true"
}
else {
    "failed"
}

$wechatHealthStatus = "unknown"
if ($runtimeReady -and $null -ne $resolvedCollectorConfigPath) {
    $locationPushed = $false
    try {
        Set-RoleMysqlPassword -RoleEnvironmentName "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD"
        Resolve-RequiredEnv -Name "WEINSIGHT_WEB_HOST" | Out-Null
        Resolve-RequiredEnv -Name "WEINSIGHT_TLS_CERTFILE" | Out-Null
        Resolve-RequiredEnv -Name "WEINSIGHT_TLS_KEYFILE" | Out-Null
        Push-Location -LiteralPath $resolvedProjectRoot
        $locationPushed = $true
        $healthArguments = @("-m", "app.main", "wechat-health", "--config", $resolvedCollectorConfigPath)
        & $python @healthArguments *> $null
        if ($LASTEXITCODE -eq 0) {
            $wechatHealthStatus = "ok"
        }
        else {
            $wechatHealthStatus = "failed"
        }
    }
    catch {
        $wechatHealthStatus = "unknown"
    }
    finally {
        if ($locationPushed) {
            Pop-Location
        }
    }
}

Write-Output ("web_task_status={0}" -f $webTaskStatus)
Write-Output ("collector_task_status={0}" -f $collectorTaskStatus)
Write-Output ("pipeline_task_status={0}" -f $pipelineTaskStatus)
Write-Output ("legacy_group_scheduler_present={0}" -f $legacyTaskPresent)
Write-Output ("web_https_reachable={0}" -f $webHttpsReachable)
Write-Output ("mysql_config_ok={0}" -f $mysqlConfigOk)
Write-Output ("wechat_health_status={0}" -f $wechatHealthStatus)
