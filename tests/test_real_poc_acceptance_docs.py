from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/真实POC验收与扩容判断.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md")


def test_real_poc_acceptance_doc_documents_expansion_gates() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "从 1 个扩到 3 个" in content
    assert "最多 20 个" in content
    assert "连续失败 3 次" in content
    assert "回滚到单账号模式" in content
    assert "日报质量" in content


def test_real_poc_acceptance_doc_documents_go_watch_no_go_rules() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Go：1 个账号和 1 个核心群都通过",
        "双链路小窗口无核心群超阈值等待",
        "Watch：存在可定位失败，但可手动恢复",
        "No-Go：任一账号连续失败 3 次，或核心群等待超过阈值",
        "3 个稳定后再考虑最多 20 个",
        "AI 仍保持 dry-run",
        "model_called=0",
        "只保留群链路",
    ]:
        assert keyword in content


def test_real_poc_acceptance_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 61: POC 验收与扩容判断" in plan
    assert "真实POC验收与扩容判断.md" in plan
