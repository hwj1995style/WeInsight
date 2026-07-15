from __future__ import annotations

from pathlib import Path


REVIEW_DOC = Path("docs/design/公众号订阅号链路启动前设计复核结论.md")
DESIGN_DOC = Path("docs/design/微信信息采集分析系统落地方案设计.md")
PLAN_DOC = Path("docs/superpowers/plans/2026-07-03-微信信息采集分析系统第三阶段运维化计划.md")


def test_article_poc_readiness_review_doc_exists_with_required_conclusion() -> None:
    assert REVIEW_DOC.exists()
    content = REVIEW_DOC.read_text(encoding="utf-8")

    for required in [
        "# 公众号订阅号链路启动前设计复核结论",
        "复核结论",
        "暂不启动公众号/订阅号真实采集",
        "允许进入受控 POC 准备",
        "wechat_ui_lock",
        "低峰执行",
        "07:30-19:30",
        "每小时执行 1 次",
        "当天发布",
        "article_hash",
        "可中断重试",
        "独立入库",
        "独立清洗",
        "独立分析",
        "核心群不超过 5 个",
        "公众号/订阅号不超过 20 个",
        "前置条件",
    ]:
        assert required in content


def test_design_doc_links_article_poc_readiness_checklist() -> None:
    content = DESIGN_DOC.read_text(encoding="utf-8")

    for required in [
        "公众号/订阅号链路启动前检查",
        "暂不启动公众号/订阅号真实采集",
        "docs/design/公众号订阅号链路启动前设计复核结论.md",
    ]:
        assert required in content


def test_phase3_plan_marks_task25_done_with_conclusion() -> None:
    content = PLAN_DOC.read_text(encoding="utf-8")

    assert "- [x] 复核公众号/订阅号链路是否仍满足 UI 锁交错规则。" in content
    assert "- [x] 给出是否进入公众号/订阅号 POC 的结论。" in content
    assert "暂不启动公众号/订阅号真实采集" in content
