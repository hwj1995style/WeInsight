param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$ConfigPath = "config\config.dev.yaml",
    [switch]$Once
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredEnv {
    param([string]$Name)

    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name, "Process"))) {
        return [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name, "User"))) {
        $value = [Environment]::GetEnvironmentVariable($Name, "User")
        [Environment]::SetEnvironmentVariable($Name, $value, "Process")
        return $value
    }
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name, "Machine"))) {
        $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
        [Environment]::SetEnvironmentVariable($Name, $value, "Process")
        return $value
    }

    throw "Missing required environment variable: $Name"
}

Resolve-RequiredEnv -Name "WEINSIGHT_MYSQL_PASSWORD" | Out-Null

$logDir = Join-Path $ProjectRoot "runtime\logs\group_scheduler"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir ("group_scheduler_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$logPattern = Join-Path $logDir "group_scheduler_YYYYMMDD.log"

$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @("-m", "app.main", "run-group-scheduler", "--config", $ConfigPath)
if ($Once) {
    $arguments += "--once"
}

Push-Location $ProjectRoot
try {
    $startLine = "[{0}] Starting group scheduler. ProjectRoot={1}; ConfigPath={2}; Once={3}" -f (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    ), $ProjectRoot, $ConfigPath, [bool]$Once
    $startLine | Tee-Object -FilePath $logFile -Append

    $rotationLine = "[{0}] log_retention_hint=logs are split by date as {1}; review and archive old files manually." -f (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    ), $logPattern
    $rotationLine | Tee-Object -FilePath $logFile -Append

    & $python @arguments 2>&1 | Tee-Object -FilePath $logFile -Append
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    $exitLine = "[{0}] scheduler_exit " -f (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    )
    $exitLine += "exit_code={0}" -f $exitCode
    $exitLine | Tee-Object -FilePath $logFile -Append

    if ($exitCode -ne 0) {
        $failedLine = "[{0}] scheduler_exit_status=failed exit_code={1}; check scheduler log and screenshots." -f (
            Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        ), $exitCode
        $failedLine | Tee-Object -FilePath $logFile -Append
    }

    exit $exitCode
}
catch {
    $errorLine = "[{0}] scheduler_exit_status=failed exit_code=1; error={1}" -f (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    ), $_.Exception.Message
    $errorLine | Tee-Object -FilePath $logFile -Append
    exit 1
}
finally {
    Pop-Location
}
