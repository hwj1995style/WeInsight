param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ConfigPath = "config\config.prod.yaml",
    [switch]$AllowSharedMysqlPasswordFallback
)

$ErrorActionPreference = "Stop"

function Resolve-OptionalEnv {
    param([string]$Name)

    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            if ($scope -ne "Process") {
                [Environment]::SetEnvironmentVariable($Name, $value, "Process")
            }
            return $value
        }
    }
    return $null
}

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

function Write-SafeLog {
    param([string]$Path, [string]$Message)

    Add-Content -LiteralPath $Path -Value $Message -Encoding UTF8
}

$logFile = $null
$locationPushed = $false
try {
    $resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $configCandidate = if ([IO.Path]::IsPathRooted($ConfigPath)) {
        $ConfigPath
    }
    else {
        Join-Path $resolvedProjectRoot $ConfigPath
    }
    $resolvedConfigPath = (Resolve-Path -LiteralPath $configCandidate).Path
    if (-not (Test-Path -LiteralPath $resolvedConfigPath -PathType Leaf)) {
        throw [System.IO.FileNotFoundException]::new("Config file is missing.")
    }
    $rootPrefix = $resolvedProjectRoot.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedConfigPath.StartsWith(
        $rootPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw [System.UnauthorizedAccessException]::new(
            "ConfigPath must stay under ProjectRoot."
        )
    }
    $modulePath = Join-Path $resolvedProjectRoot "app\web\__main__.py"
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw [System.IO.FileNotFoundException]::new("Web module is missing.")
    }

    $logDir = Join-Path $resolvedProjectRoot "runtime\logs\admin_web"
    [IO.Directory]::CreateDirectory($logDir) | Out-Null
    $logFile = Join-Path $logDir (
        "admin_web_{0}.log" -f (Get-Date -Format "yyyyMMdd")
    )

    $mysqlPassword = Resolve-OptionalEnv -Name "WEINSIGHT_WEB_MYSQL_PASSWORD"
    if ([string]::IsNullOrWhiteSpace($mysqlPassword)) {
        if (-not $AllowSharedMysqlPasswordFallback) {
            throw [System.InvalidOperationException]::new(
                "Role-specific MySQL password is required."
            )
        }
        # Compatibility fallback for development or legacy manual launches only.
        $mysqlPassword = Resolve-RequiredEnv -Name "WEINSIGHT_MYSQL_PASSWORD"
    }
    [Environment]::SetEnvironmentVariable("WEINSIGHT_MYSQL_PASSWORD", $mysqlPassword, "Process")
    Resolve-RequiredEnv -Name "WEINSIGHT_WEB_HOST" | Out-Null
    Resolve-RequiredEnv -Name "WEINSIGHT_TLS_CERTFILE" | Out-Null
    Resolve-RequiredEnv -Name "WEINSIGHT_TLS_KEYFILE" | Out-Null

    $python = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    $arguments = @("-m", "app.web", "--config", $resolvedConfigPath)
    Write-SafeLog -Path $logFile -Message (
        "[{0}] process_start process=admin_web module=app.web config_path={1}" -f (
            Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        ), $resolvedConfigPath
    )

    Push-Location -LiteralPath $resolvedProjectRoot
    $locationPushed = $true
    & $python @arguments *> $null
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 1
    }
    $exitSummary = "exit_code={0}" -f $exitCode
    Write-SafeLog -Path $logFile -Message (
        "[{0}] process_exit process=admin_web {1}" -f (
            Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        ), $exitSummary
    )
    exit $exitCode
}
catch {
    $exceptionType = $_.Exception.GetType().Name
    if ($null -ne $logFile) {
        Write-SafeLog -Path $logFile -Message (
            "[{0}] process_failed process=admin_web exception_type={1} exit_code={2}" -f (
                Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            ), $exceptionType, 1
        )
    }
    [Console]::Error.WriteLine(
        "startup_failed process=admin_web exception_type={0}" -f $exceptionType
    )
    exit 1
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
}
