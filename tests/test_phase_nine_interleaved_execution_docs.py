from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/第九阶段双链路交错真实小窗口验证记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_phase_nine_interleaved_doc_documents_group_priority() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "1 到 2 小时",
        "群链路优先",
        "article 链路可中断",
        "核心群等待超过阈值",
        "wechat_ui_lock",
        "只保留群链路",
    ]:
        assert keyword in content


def test_phase_nine_interleaved_doc_documents_metrics_and_rollback_rules() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Task 64",
        "Task 65",
        "每 15 分钟",
        "trial-monitor-report",
        "group-runtime-metrics",
        "article-runtime-metrics",
        "group-task-failed-list",
        "article-task-failed-list",
        "回滚到单账号模式",
        "Go / Watch / No-Go",
        "model_called=0",
    ]:
        assert keyword in content


def test_phase_nine_interleaved_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 66: 双链路交错真实小窗口验证" in plan
    assert "第九阶段双链路交错真实小窗口验证记录.md" in plan
