from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/第九阶段单核心群真实轮询POC执行记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_phase_nine_single_group_execution_doc_limits_scope() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "1 个实际授权核心群",
        "group-config-upsert",
        "collect-group-once",
        "run-group-scheduler --once",
        "group-runtime-summary",
        "group-runtime-metrics",
        "截图",
        "去重",
    ]:
        assert keyword in content


def test_phase_nine_single_group_execution_doc_documents_safe_execution() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Task 63",
        "真实POC环境核验记录.md",
        "手动命令触发",
        "有人值守",
        "不注册 Windows 计划任务",
        "不启用无人值守",
        "不启动 article 链路",
        "wechat_ui_lock",
        "连续失败 3 次",
        "AI 继续 dry-run",
        "model_called=0",
        "Go / Watch / No-Go",
    ]:
        assert keyword in content


def test_phase_nine_single_group_execution_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 65: 单核心群真实轮询 POC 执行" in plan
    assert "第九阶段单核心群真实轮询POC执行记录.md" in plan
