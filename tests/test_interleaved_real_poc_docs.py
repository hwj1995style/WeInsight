from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/双链路交错小窗口验证记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md")


def test_interleaved_real_poc_doc_documents_group_priority() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "1 到 2 小时" in content
    assert "群链路优先" in content
    assert "article 链路可中断" in content
    assert "核心群等待超过阈值" in content
    assert "trial-monitor-report" in content


def test_interleaved_real_poc_doc_documents_ui_lock_and_pause_rules() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "article 链路不得长时间占用微信 UI",
        "核心群等待超过阈值立即暂停 article 链路",
        "wechat_ui_lock",
        "group-runtime-metrics",
        "article-runtime-metrics",
        "group-task-failed-list",
        "article-task-failed-list",
        "只保留群链路",
        "回滚到单账号模式",
        "Go / Watch / No-Go",
    ]:
        assert keyword in content


def test_interleaved_real_poc_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 60: 双链路交错小窗口验证" in plan
    assert "双链路交错小窗口验证记录.md" in plan
