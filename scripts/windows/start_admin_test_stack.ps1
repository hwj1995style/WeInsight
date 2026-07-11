param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ConfigPath = "config\config.e2e.yaml",
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$runtimeDirName = "runtime\test\admin_stack"

function Test-LoopbackHost([string]$HostName) {
    return $HostName -in @("127.0.0.1", "localhost", "::1")
}

function Stop-OwnedProcesses([string]$PidDirectory) {
    if (-not (Test-Path -LiteralPath $PidDirectory)) { return }
    Get-ChildItem -LiteralPath $PidDirectory -Filter "*.pid.json" | ForEach-Object {
        $metadata = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$metadata.pid) -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.ProcessName -match "^python") {
            $actualStart = $process.StartTime.ToUniversalTime().ToString("o")
            if ($actualStart -eq $metadata.start_time_utc) {
                Stop-Process -Id $process.Id
                $process.WaitForExit(5000) | Out-Null
            }
        }
        Remove-Item -LiteralPath $_.FullName -Force
    }
}

$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$configCandidate = if ([IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath } else { Join-Path $root $ConfigPath }
$config = (Resolve-Path -LiteralPath $configCandidate).Path
$rootPrefix = $root.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if (-not $config.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "ConfigPath must stay under ProjectRoot." }
$runtimeDir = Join-Path $root $runtimeDirName

if ($Stop) { Stop-OwnedProcesses $runtimeDir; exit 0 }

# Fail closed before the first Start-Process. The validator uses the project's
# real config loader and emits only non-secret gate values.
$validator = @'
import json, sys
from pathlib import Path
from app.core.config import load_config
c = load_config(Path(sys.argv[1]))
print(json.dumps({"env": c.app.env, "mode": c.workers.collector_mode,
 "web_host": c.web.host, "web_port": c.web.port, "secure": c.web.secure_cookie,
 "mysql_host": c.mysql.host, "mysql_db": c.mysql.database}))
'@
$gate = (& python -c $validator $config | ConvertFrom-Json)
if ($gate.env -ne "dev") { throw "Test stack requires app.env=dev." }
if ($gate.mode -ne "fake") { throw "Test stack requires collector_mode=fake." }
if (-not (Test-LoopbackHost $gate.web_host)) { throw "Web host must be loopback." }
if ($gate.secure) { throw "Test stack requires secure_cookie=false." }
if (-not (Test-LoopbackHost $gate.mysql_host)) { throw "MySQL must be loopback." }
if ($gate.mysql_db -match "(?i)prod|production") { throw "Production-like database name rejected." }
if ($gate.mysql_db -notmatch "(?i)test|e2e") { throw "Test stack requires a disposable test/e2e database." }

[IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
Stop-OwnedProcesses $runtimeDir
$started = @()
try {
    foreach ($role in @(
        @{ name="web"; module="app.web" },
        @{ name="collector"; module="app.workers.collector_main" },
        @{ name="pipeline"; module="app.workers.pipeline_main" }
    )) {
        $stdout = Join-Path $runtimeDir ($role.name + ".stdout.log")
        $stderr = Join-Path $runtimeDir ($role.name + ".stderr.log")
        $process = Start-Process -FilePath "python" -ArgumentList @("-m", $role.module, "--config", $config) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $started += $process
        @{ pid=$process.Id; module=$role.module; start_time_utc=$process.StartTime.ToUniversalTime().ToString("o") } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir ($role.name + ".pid.json")) -Encoding UTF8
    }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        try { $response = Invoke-WebRequest -UseBasicParsing -Uri ("http://{0}:{1}/healthz" -f $gate.web_host, $gate.web_port) -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch { }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Fake admin Web did not become ready before timeout."
} catch {
    Stop-OwnedProcesses $runtimeDir
    throw
}
