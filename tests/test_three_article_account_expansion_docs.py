from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/三公众号订阅号扩容配置记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_three_article_account_expansion_doc_documents_limits() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "3 个实际授权公众号/订阅号",
        "article-account-upsert",
        "article-account-list",
        "article-account-disable",
        "任一账号失败都可单独关闭",
        "不启用无人值守",
    ]:
        assert keyword in content


def test_three_article_account_expansion_doc_documents_gate_and_rollback() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Task 67",
        "第九阶段真实POC验收报告.md",
        "Go 结论",
        "授权公众号名称A",
        "授权公众号名称B",
        "授权公众号名称C",
        "每小时最多执行 1 次",
        "每轮最多 3 篇",
        "只采集当天发布数据",
        "最多 20 个只做后续评估",
        "回滚到单账号模式",
        "model_called=0",
    ]:
        assert keyword in content


def test_three_article_account_expansion_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 68: 3 个公众号/订阅号扩容配置" in plan
    assert "三公众号订阅号扩容配置记录.md" in plan
