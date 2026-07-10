from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-06-微信信息采集分析系统第六阶段清洗和日报计划.md")
DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")
SUMMARY_DESIGN = Path("docs/design/汇总日报只读聚合层设计.md")
SUMMARY_RUNBOOK = Path("docs/operations/汇总日报运行手册.md")
README = Path("README.md")


def test_phase_six_plan_is_documented() -> None:
    assert PLAN.exists()

    content = PLAN.read_text(encoding="utf-8")

    assert "第六阶段清洗和日报" in content
    for task_name in [
        "Task 41: 阶段六设计和实施计划",
        "Task 42: article 分析结果表和迁移",
        "Task 43: article 基础摘要和标签分析",
        "Task 44: article 日报生成",
        "Task 45: article 日报查看和导出",
        "Task 46: 汇总日报只读聚合层设计",
    ]:
        assert task_name in content

    assert "汇总日报失败不得回写 group/article 链路状态" in content


def test_phase_six_design_and_readme_reference_plan() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "第六阶段清洗和日报" in design
    assert "2026-07-06-微信信息采集分析系统第六阶段清洗和日报计划.md" in design
    assert "2026-07-06-微信信息采集分析系统第六阶段清洗和日报计划.md" in readme


def test_phase_six_documents_transient_article_body_policy() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    for content in [plan, design, readme]:
        assert "运行时临时读取正文" in content
        assert "落库只保存摘要和结构化特征" in content
        assert "不保存正文或 HTML" in content


def test_task_43_documents_three_layer_article_extraction_strategy() -> None:
    content = PLAN.read_text(encoding="utf-8")

    assert "正文文本 + HTML 表格 + 图片 OCR 表格" in content
    assert "html_table" in content
    assert "image_ocr" in content
    assert "extracted_tables_json" in content
    assert "price_items_json" in content


def test_summary_report_design_is_read_only() -> None:
    content = SUMMARY_DESIGN.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert "只读聚合层" in content
    assert "读取 wechat_group_daily_report" in content
    assert "读取 wechat_article_daily_report" in content
    assert "不得更新 wechat_group_process_task" in content
    assert "不得更新 wechat_article_process_task" in content
    assert "汇总日报失败不得回写 group/article 链路状态" in content
    assert "汇总日报只读聚合层设计.md" in design


def test_summary_report_implementation_tasks_are_planned() -> None:
    content = PLAN.read_text(encoding="utf-8")

    for task_name in [
        "Task 47: 汇总日报只读查询 repo",
        "Task 48: 汇总日报 Markdown 组装服务",
        "Task 49: 汇总日报 CLI 查看和导出",
        "Task 50: 汇总日报运维文档和隔离回归",
    ]:
        assert task_name in content

    for expected in [
        "MysqlSummaryDailyReportQueryRepo",
        "SummaryDailyReportService",
        "summary-daily-report-show",
        "summary-daily-report-export",
        "runtime/reports/summary",
    ]:
        assert expected in content


def test_summary_report_runbook_documents_read_only_operation() -> None:
    content = SUMMARY_RUNBOOK.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "summary-daily-report-show" in content
    assert "summary-daily-report-export" in content
    assert "runtime/reports/summary" in content
    assert "只读取 wechat_group_daily_report 和 wechat_article_daily_report" in content
    assert "汇总日报失败不得回写 group/article 链路状态" in content
    assert "汇总日报不占用微信 UI" in content
    assert "汇总日报运行手册.md" in readme
