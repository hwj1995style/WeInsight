from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SCRIPTS = (
    ROOT / "scripts" / "windows" / "start_group_scheduler.ps1",
    ROOT / "scripts" / "windows" / "register_group_scheduler_task.ps1",
    ROOT / "scripts" / "windows" / "unregister_group_scheduler_task.ps1",
)
ADMIN_STACK_SCRIPTS = tuple(
    ROOT / "scripts" / "windows" / name
    for name in (
        "start_admin_web.ps1",
        "start_collector_worker.ps1",
        "start_pipeline_worker.ps1",
        "register_admin_stack.ps1",
        "unregister_admin_stack.ps1",
        "check_admin_stack.ps1",
    )
)


def _parse_powershell_script(script: Path) -> subprocess.CompletedProcess[str]:
    command = (
        "$errors = @(); "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 "
        "}"
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )


def test_windows_scheduler_scripts_are_valid_powershell() -> None:
    for script in WINDOWS_SCRIPTS:
        result = _parse_powershell_script(script)
        assert result.returncode == 0, result.stderr


def test_admin_stack_scripts_are_valid_powershell() -> None:
    for script in ADMIN_STACK_SCRIPTS:
        assert script.exists(), script
        result = _parse_powershell_script(script)
        assert result.returncode == 0, result.stderr


def test_start_group_scheduler_script_requires_mysql_password_env() -> None:
    script = ROOT / "scripts" / "windows" / "start_group_scheduler.ps1"

    content = script.read_text(encoding="utf-8")

    assert "WEINSIGHT_MYSQL_PASSWORD" in content
    assert "run-group-scheduler" in content
    assert "runtime\\logs\\group_scheduler" in content
    assert "weinsight_dev" not in content


def test_start_group_scheduler_script_records_log_rotation_and_exit_code() -> None:
    script = ROOT / "scripts" / "windows" / "start_group_scheduler.ps1"

    content = script.read_text(encoding="utf-8")

    assert "log_retention_hint" in content
    assert "group_scheduler_YYYYMMDD.log" in content
    assert "exit_code={0}" in content
    assert "$exitCode = $LASTEXITCODE" in content
    assert "scheduler_exit_status=failed" in content
    assert "exit $exitCode" in content


def test_start_group_scheduler_script_does_not_register_scheduled_task() -> None:
    script = ROOT / "scripts" / "windows" / "start_group_scheduler.ps1"

    content = script.read_text(encoding="utf-8")

    assert "Register-ScheduledTask" not in content
    assert "New-ScheduledTaskTrigger" not in content
    assert "register_group_scheduler_task.ps1" not in content


def test_register_group_scheduler_task_uses_start_script() -> None:
    script = ROOT / "scripts" / "windows" / "register_group_scheduler_task.ps1"

    content = script.read_text(encoding="utf-8")

    assert "Register-ScheduledTask" in content
    assert "New-ScheduledTaskTrigger" in content
    assert "start_group_scheduler.ps1" in content
    assert "WEINSIGHT_MYSQL_PASSWORD" in content
