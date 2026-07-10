from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/真实POC环境核验记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_real_poc_environment_check_doc_records_required_gates() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "微信 PC 4.1.8.107",
        "微信自动更新已关闭",
        "check-config",
        "wechat-health",
        "trial-monitor-report",
        "group-runtime-metrics",
        "article-runtime-metrics",
        "Go / No-Go",
    ]:
        assert keyword in content


def test_real_poc_environment_check_doc_keeps_execution_controlled() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "不注册 Windows 计划任务",
        "不启用无人值守",
        "AI 继续 dry-run",
        "model_called=0",
        "1 个实际授权公众号/订阅号",
        "1 个实际授权核心群",
        "wechat_ui_lock",
        "核心群等待超过阈值",
        "任一账号连续失败 3 次",
        "只保留群链路",
    ]:
        assert keyword in content


def test_real_poc_environment_check_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 63: 真实 POC 环境核验" in plan
    assert "真实POC环境核验记录.md" in plan
