from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/三账号验收与二十账号扩容判断.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_three_account_acceptance_doc_documents_20_account_gate() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "4 个小规模账号稳定后再考虑最多 20 个",
        "最多 20 个只做后续评估",
        "回滚到单账号模式",
        "只保留群链路",
        "日报质量",
        "Go / Watch / No-Go",
    ]:
        assert keyword in content


def test_three_account_acceptance_doc_documents_decision_rules() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Task 69",
        "三账号小规模交错POC运行记录.md",
        "Go：4 个账号和核心群交错稳定",
        "Watch：存在可定位失败，可单账号关闭并继续观察",
        "No-Go：任一账号连续失败 3 次，或核心群等待超过阈值",
        "扩容：最多 20 个只进入后续设计，不在第九阶段直接启用",
        "trial-monitor-report",
        "article-runtime-metrics",
        "group-runtime-metrics",
        "model_called=0",
    ]:
        assert keyword in content


def test_three_account_acceptance_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 70: 3 账号验收与最多 20 个扩容判断" in plan
    assert "三账号验收与二十账号扩容判断.md" in plan
