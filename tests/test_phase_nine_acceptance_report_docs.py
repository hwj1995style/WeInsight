from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/第九阶段真实POC验收报告.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_phase_nine_acceptance_report_doc_documents_decision() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Go / Watch / No-Go",
        "从 1 个扩到 3 个",
        "日报质量",
        "核心群等待超过阈值",
        "任一账号连续失败 3 次",
        "model_called=0",
    ]:
        assert keyword in content


def test_phase_nine_acceptance_report_doc_contains_required_decision_table() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "单公众号/订阅号真实执行",
        "单核心群真实执行",
        "双链路交错小窗口",
        "UI 锁",
        "AI dry-run",
        "回滚演练",
        "允许进入 Task 68",
        "回滚到单账号模式",
        "只保留群链路",
        "最多 20 个只做后续评估",
    ]:
        assert keyword in content


def test_phase_nine_acceptance_report_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 67: 真实 POC 验收报告落地" in plan
    assert "第九阶段真实POC验收报告.md" in plan
