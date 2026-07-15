from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "scripts" / "windows"
START_SCRIPTS = {
    "admin_web": (
        WINDOWS_DIR / "start_admin_web.ps1",
        "app.web",
        r"runtime\logs\admin_web",
        r"app\web\__main__.py",
    ),
    "collector_worker": (
        WINDOWS_DIR / "start_collector_worker.ps1",
        "app.workers.collector_main",
        r"runtime\logs\collector_worker",
        r"app\workers\collector_main.py",
    ),
    "pipeline_worker": (
        WINDOWS_DIR / "start_pipeline_worker.ps1",
        "app.workers.pipeline_main",
        r"runtime\logs\pipeline_worker",
        r"app\workers\pipeline_main.py",
    ),
}
ROLE_MYSQL_ENV = {
    "admin_web": "WEINSIGHT_WEB_MYSQL_PASSWORD",
    "collector_worker": "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD",
    "pipeline_worker": "WEINSIGHT_PIPELINE_MYSQL_PASSWORD",
}
TASK_NAMES = (
    "WeInsight-Admin-Web",
    "WeInsight-Collector-Worker",
    "WeInsight-Pipeline-Worker",
)
LEGACY_TASK_NAMES = (
    "WeInsight-Group-Scheduler",
    "WeInsight Group Scheduler",
)
CHECK_KEYS = (
    "web_task_status",
    "collector_task_status",
    "pipeline_task_status",
    "legacy_group_scheduler_present",
    "web_https_reachable",
    "mysql_config_ok",
    "wechat_health_status",
)


def _content(path: Path) -> str:
    assert path.exists(), path
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("process_name", "script", "module", "log_dir", "module_file"),
    [
        (process_name, *values)
        for process_name, values in START_SCRIPTS.items()
    ],
)
def test_start_scripts_use_safe_environment_command_and_paths(
    process_name: str,
    script: Path,
    module: str,
    log_dir: str,
    module_file: str,
) -> None:
    content = _content(script)

    assert '$ErrorActionPreference = "Stop"' in content
    assert "function Resolve-RequiredEnv" in content
    assert 'GetEnvironmentVariable($Name, "Process")' in content
    assert 'GetEnvironmentVariable($Name, "User")' in content
    assert 'GetEnvironmentVariable($Name, "Machine")' in content
    assert 'SetEnvironmentVariable($Name, $value, "Process")' in content
    assert 'Resolve-RequiredEnv -Name "WEINSIGHT_MYSQL_PASSWORD"' in content
    assert "Get-Command python" in content
    assert '$arguments = @("-m", "' + module + '"' in content
    assert "& $python @arguments" in content
    assert log_dir in content
    assert module_file in content
    assert 'Get-Date -Format "yyyyMMdd"' in content
    assert "exit_code={0}" in content
    assert "exception_type={0}" in content
    assert ".Exception.GetType().Name" in content
    assert "Resolve-Path -LiteralPath" in content
    assert "Test-Path -LiteralPath" in content
    assert "Push-Location -LiteralPath" in content
    assert "Invoke-Expression" not in content
    assert "Remove-Item" not in content
    assert "Register-ScheduledTask" not in content
    assert ".Exception.Message" not in content
    assert "weinsight_dev" not in content
    assert not re.search(r"[A-Za-z]:\\.*python(?:\.exe)?", content, re.IGNORECASE)
    assert process_name in content


def test_admin_web_start_requires_tls_environment_without_logging_values() -> None:
    content = _content(START_SCRIPTS["admin_web"][0])

    for name in (
        "WEINSIGHT_WEB_HOST",
        "WEINSIGHT_TLS_CERTFILE",
        "WEINSIGHT_TLS_KEYFILE",
    ):
        assert f'Resolve-RequiredEnv -Name "{name}"' in content
        assert f"{name}=" not in content


def test_start_scripts_do_not_copy_child_tracebacks_into_wrapper_logs() -> None:
    for script, *_ in START_SCRIPTS.values():
        content = _content(script)

        assert "& $python @arguments *> $null" in content
        assert "& $python @arguments 2>&1" not in content
        assert "Add-Content -LiteralPath $logFile -Value ([string]$_)" not in content


def test_all_config_paths_are_required_to_be_files() -> None:
    for script, *_ in START_SCRIPTS.values():
        content = _content(script)
        assert (
            "Test-Path -LiteralPath $resolvedConfigPath -PathType Leaf"
        ) in content

    for script_name in ("register_admin_stack.ps1", "check_admin_stack.ps1"):
        content = _content(WINDOWS_DIR / script_name)
        assert "Test-Path -LiteralPath $resolvedPath -PathType Leaf" in content


@pytest.mark.parametrize("process_name", list(START_SCRIPTS))
def test_start_scripts_prefer_role_mysql_password_with_compatibility_fallback(
    process_name: str,
) -> None:
    content = _content(START_SCRIPTS[process_name][0])
    role_env = ROLE_MYSQL_ENV[process_name]

    assert "[switch]$AllowSharedMysqlPasswordFallback" in content
    assert f'Resolve-OptionalEnv -Name "{role_env}"' in content
    assert 'Resolve-RequiredEnv -Name "WEINSIGHT_MYSQL_PASSWORD"' in content
    assert content.index(role_env) < content.index("WEINSIGHT_MYSQL_PASSWORD")
    assert "if (-not $AllowSharedMysqlPasswordFallback)" in content
    assert "Role-specific MySQL password is required." in content
    assert (
        '[Environment]::SetEnvironmentVariable('
        '"WEINSIGHT_MYSQL_PASSWORD", $mysqlPassword, "Process")'
    ) in content
    assert f"{role_env}=" not in content


@pytest.mark.parametrize("process_name", ["collector_worker", "pipeline_worker"])
def test_worker_start_scripts_do_not_require_or_log_tls_values(
    process_name: str,
) -> None:
    content = _content(START_SCRIPTS[process_name][0])

    assert "WEINSIGHT_WEB_HOST" not in content
    assert "WEINSIGHT_TLS_CERTFILE" not in content
    assert "WEINSIGHT_TLS_KEYFILE" not in content


def test_register_preflights_legacy_names_paths_and_environment_first() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")
    first_register = content.index("Register-ScheduledTask")

    for task_name in LEGACY_TASK_NAMES:
        assert task_name in content
        assert content.index(task_name) < first_register
    for task_name in TASK_NAMES:
        assert task_name in content
    for script_name in (
        "start_admin_web.ps1",
        "start_collector_worker.ps1",
        "start_pipeline_worker.ps1",
    ):
        assert script_name in content
        assert content.index(script_name) < first_register
    for env_name in (
        "WEINSIGHT_WEB_MYSQL_PASSWORD",
        "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD",
        "WEINSIGHT_PIPELINE_MYSQL_PASSWORD",
        "WEINSIGHT_WEB_HOST",
        "WEINSIGHT_TLS_CERTFILE",
        "WEINSIGHT_TLS_KEYFILE",
    ):
        assert env_name in content
        assert content.index(env_name) < first_register

    assert "Resolve-Path -LiteralPath" in content
    assert "Test-Path -LiteralPath" in content
    assert content.count("Register-ScheduledTask") == 3
    assert "Invoke-Expression" not in content
    assert "Remove-Item" not in content
    assert "Unregister-ScheduledTask" not in content


def test_register_legacy_query_fails_closed_before_name_matching() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")

    query = "$allScheduledTasks = @(Get-ScheduledTask -ErrorAction Stop)"
    assert query in content
    assert "Get-ScheduledTask `" not in content
    assert "-ErrorAction SilentlyContinue" not in content
    assert "Where-Object { $_.TaskName -eq $legacyTaskName }" in content
    assert content.index(query) < content.index("foreach ($legacyTaskName")
    assert content.index(query) < content.index("Register-ScheduledTask")


def test_register_requires_persisted_environment_for_future_logons() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")

    assert "function Resolve-PersistedRequiredEnv" in content
    assert 'GetEnvironmentVariable($Name, "User")' in content
    assert 'GetEnvironmentVariable($Name, "Machine")' in content
    assert 'GetEnvironmentVariable($Name, "Process")' not in content
    for env_name in (
        "WEINSIGHT_WEB_MYSQL_PASSWORD",
        "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD",
        "WEINSIGHT_PIPELINE_MYSQL_PASSWORD",
        "WEINSIGHT_WEB_HOST",
        "WEINSIGHT_TLS_CERTFILE",
        "WEINSIGHT_TLS_KEYFILE",
    ):
        assert f'Resolve-PersistedRequiredEnv -Name "{env_name}"' in content


def test_register_supports_distinct_config_paths_for_three_actions() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")

    assert "[string]$WebConfigPath" in content
    assert "[string]$CollectorConfigPath" in content
    assert "[string]$PipelineConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $WebConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $CollectorConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $PipelineConfigPath" in content
    assert "-ResolvedConfigPath $resolvedWebConfigPath" in content
    assert "-ResolvedConfigPath $resolvedCollectorConfigPath" in content
    assert "-ResolvedConfigPath $resolvedPipelineConfigPath" in content


def test_register_uses_fixed_interactive_limited_task_contract() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")

    assert "$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()" in content
    assert "$currentUser = $currentIdentity.Name" in content
    assert "[string]::IsNullOrWhiteSpace($currentUser)" in content
    assert "[Environment]::UserInteractive" in content
    assert "$currentIdentity.IsSystem" in content
    assert '"NT AUTHORITY\\"' in content
    assert '"NT SERVICE\\"' in content
    assert "service or non-interactive identity" in content
    assert "New-ScheduledTaskPrincipal" in content
    assert "-UserId $currentUser" in content
    assert "-LogonType Interactive" in content
    assert "-RunLevel Limited" in content
    assert "-Principal $principal" in content
    assert "New-ScheduledTaskTrigger -AtLogOn -User $currentUser" in content
    assert "$env:USERNAME" not in content
    assert "-MultipleInstances IgnoreNew" in content
    assert "-RestartCount 3" in content
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in content
    assert "-ExecutionTimeLimit (New-TimeSpan -Days 0)" in content
    assert "SYSTEM" not in content
    assert "ServiceAccount" not in content
    assert "-RunLevel Highest" not in content
    assert '-File "{0}" -ProjectRoot "{1}" -ConfigPath "{2}"' in content

    identity_check = content.index("$currentIdentity.IsSystem")
    interactive_check = content.index("[Environment]::UserInteractive")
    principal_build = content.index("$principal = New-ScheduledTaskPrincipal")
    assert identity_check < principal_build
    assert interactive_check < principal_build


def test_scheduled_actions_do_not_opt_in_to_shared_mysql_password() -> None:
    content = _content(WINDOWS_DIR / "register_admin_stack.ps1")

    assert "AllowSharedMysqlPasswordFallback" not in content


def test_unregister_only_targets_three_fixed_admin_stack_tasks() -> None:
    content = _content(WINDOWS_DIR / "unregister_admin_stack.ps1")

    for task_name in TASK_NAMES:
        assert content.count(task_name) == 1
    for legacy_name in LEGACY_TASK_NAMES:
        assert legacy_name not in content
    assert "foreach ($taskName in $taskNames)" in content
    assert "Unregister-ScheduledTask -TaskName $taskName -Confirm:$false" in content
    assert "Remove-Item" not in content
    assert "Invoke-Expression" not in content
    assert "scripts" not in content.lower()
    assert "runtime" not in content.lower()
    assert "database" not in content.lower()
    assert "certificate" not in content.lower()


def test_check_script_outputs_exact_read_only_health_contract() -> None:
    content = _content(WINDOWS_DIR / "check_admin_stack.ps1")

    for key in CHECK_KEYS:
        assert content.count(f'"{key}={{0}}"') == 1
    for task_name in (*TASK_NAMES, *LEGACY_TASK_NAMES):
        assert task_name in content

    assert '$webUri = "https://' in content
    assert "Invoke-WebRequest" in content
    assert "-UseBasicParsing" in content
    assert '"-m", "app.main", "check-config"' in content
    assert '"-m", "app.main", "wechat-health"' in content
    assert "Get-Command python" in content
    assert "Get-ScheduledTask" in content
    assert "Resolve-Path -LiteralPath" in content
    assert "Test-Path -LiteralPath" in content

    forbidden = (
        "collect-group-once",
        "collect-article-once",
        "run-group-scheduler",
        "run-article-scheduler",
        "app.workers",
        "start_admin_web.ps1",
        "start_collector_worker.ps1",
        "start_pipeline_worker.ps1",
        "Register-ScheduledTask",
        "Unregister-ScheduledTask",
        "Invoke-Expression",
        "Remove-Item",
        "SkipCertificateCheck",
        "ServerCertificateValidationCallback",
        "TrustAllCertsPolicy",
    )
    for marker in forbidden:
        assert marker not in content


def test_check_script_validates_three_role_configs_without_logging_passwords() -> None:
    content = _content(WINDOWS_DIR / "check_admin_stack.ps1")

    assert "[string]$WebConfigPath" in content
    assert "[string]$CollectorConfigPath" in content
    assert "[string]$PipelineConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $WebConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $CollectorConfigPath" in content
    assert "Resolve-StackConfigPath -RequestedPath $PipelineConfigPath" in content
    for role_env in ROLE_MYSQL_ENV.values():
        assert role_env in content
        assert f"{role_env}=" not in content
    assert "$resolvedWebConfigPath" in content
    assert "$resolvedCollectorConfigPath" in content
    assert "$resolvedPipelineConfigPath" in content
    assert "$allConfigChecksSucceeded = $true" in content
    assert "$allConfigChecksSucceeded = $false" in content
    assert "$mysqlConfigOk = if ($allConfigChecksSucceeded)" in content
    assert (
        '[Environment]::SetEnvironmentVariable('
        '"WEINSIGHT_MYSQL_PASSWORD", $mysqlPassword, "Process")'
    ) in content


def test_check_script_uses_collector_role_and_config_for_wechat_health() -> None:
    content = _content(WINDOWS_DIR / "check_admin_stack.ps1")

    assert (
        'Set-RoleMysqlPassword -RoleEnvironmentName '
        '"WEINSIGHT_COLLECTOR_MYSQL_PASSWORD"'
    ) in content


def test_check_rejects_noncanonical_ipv4_before_https_probe() -> None:
    content = _content(WINDOWS_DIR / "check_admin_stack.ps1")

    assert "$HostName -ne $HostName.Trim()" in content
    assert "$address.ToString() -ne $HostName" in content
    assert (
        '"-m", "app.main", "wechat-health", "--config", '
        '$resolvedCollectorConfigPath'
    ) in content


def test_all_admin_stack_scripts_avoid_destructive_and_shell_eval_commands() -> None:
    for script in (
        *(value[0] for value in START_SCRIPTS.values()),
        WINDOWS_DIR / "register_admin_stack.ps1",
        WINDOWS_DIR / "unregister_admin_stack.ps1",
        WINDOWS_DIR / "check_admin_stack.ps1",
    ):
        content = _content(script)
        assert "Invoke-Expression" not in content
        assert "Remove-Item" not in content
        assert "Move-Item" not in content
        assert "cmd.exe" not in content.lower()
        assert "Start-Process" not in content
