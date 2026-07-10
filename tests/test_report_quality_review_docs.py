from __future__ import annotations

from pathlib import Path

import yaml

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/日报质量人工评估表.md")
CONFIG = Path("config/report_quality_review.yaml")


def test_report_quality_review_template_documents_required_dimensions() -> None:
    content = DOC.read_text(encoding="utf-8")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    for keyword in ["群日报", "文章日报", "汇总日报", "准确性", "噪声", "可读性", "人工复盘", "阈值调整"]:
        assert keyword in content

    assert config["review_version"] == "v1"
    assert config["score_scale"] == {"min": 1, "max": 5}

    sections = config["sections"]
    assert "group_daily_report" in sections
    assert "article_daily_report" in sections
    assert "summary_daily_report" in sections

    assert sections["group_daily_report"]["dimensions"] == [
        "demand_supply_accuracy",
        "keyword_noise",
        "contact_masking",
        "readability",
    ]
    assert sections["article_daily_report"]["dimensions"] == [
        "summary_usefulness",
        "tag_accuracy",
        "table_extraction_quality",
        "ocr_table_quality",
        "readability",
    ]
    assert sections["summary_daily_report"]["dimensions"] == [
        "overview_usefulness",
        "cross_link_balance",
        "actionability",
    ]


def test_report_quality_review_thresholds_document_go_no_go_rules() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    thresholds = config["quality_thresholds"]
    assert thresholds["pass_min_average_score"] == 4.0
    assert thresholds["watch_min_average_score"] == 3.0
    assert thresholds["pause_below_average_score"] == 3.0
    assert thresholds["critical_dimension_min_score"] == 2
    assert "pause_article_link" in config["threshold_adjustment_rules"]
    assert "keep_manual_review" in config["threshold_adjustment_rules"]


def test_report_quality_review_doc_is_covered_by_sensitive_output_guard() -> None:
    assert DOC.as_posix() in USER_FACING_DOC_PATHS
