from __future__ import annotations

from datetime import date, datetime

from app.domain.group_analysis import DailyReportStats, analyze_clean_group_message, build_group_daily_report
from app.domain.group_cleaning import CleanGroupMessage


def _clean_message(
    *,
    msg_hash: str = "hash-1",
    clean_content: str,
    sender_hash: str | None = "sender-hash",
    msg_time_inferred: datetime | None = None,
    clean_time: datetime = datetime(2026, 7, 3, 9, 15, 0),
    has_phone: bool = False,
    has_wechat_id: bool = False,
) -> CleanGroupMessage:
    return CleanGroupMessage(
        msg_hash=msg_hash,
        group_name="核心群A",
        sender_hash=sender_hash,
        sender_display="张***",
        msg_time_display="09:15",
        msg_time_inferred=msg_time_inferred,
        msg_type="text",
        clean_content=clean_content,
        content_length=len(clean_content),
        is_empty=clean_content == "",
        has_phone=has_phone,
        has_wechat_id=has_wechat_id,
        clean_version="v1",
        source_collect_batch_id="batch-1",
        clean_time=clean_time,
    )


def test_analyze_clean_group_message_detects_demand_and_contact() -> None:
    clean = _clean_message(clean_content="求深圳兼职，需要今天到岗，联系 138****5678", has_phone=True)

    analysis = analyze_clean_group_message(clean, analyze_time=datetime(2026, 7, 3, 10, 0, 0))

    assert analysis.intent_type == "demand"
    assert analysis.has_contact is True
    assert analysis.activity_date == date(2026, 7, 3)
    assert analysis.activity_hour == 9
    assert "求" in analysis.keyword_hits
    assert "需要" in analysis.keyword_hits
    assert "深圳" in analysis.keyword_hits
    assert analysis.region_hits == ["深圳"]
    assert analysis.category_hits == ["兼职"]
    assert analysis.opportunity_hits == []
    assert analysis.opportunity_score == 4


def test_analyze_clean_group_message_detects_supply_neutral_and_empty() -> None:
    supply = analyze_clean_group_message(
        _clean_message(msg_hash="hash-2", clean_content="供应深圳岗位，有货"),
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
    )
    neutral = analyze_clean_group_message(
        _clean_message(msg_hash="hash-3", clean_content="大家早上好"),
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
    )
    empty = analyze_clean_group_message(
        _clean_message(msg_hash="hash-4", clean_content=""),
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
    )

    assert supply.intent_type == "supply"
    assert "供应" in supply.keyword_hits
    assert neutral.intent_type == "neutral"
    assert empty.intent_type == "empty"


def test_analyze_clean_group_message_prefers_inferred_message_time() -> None:
    clean = _clean_message(
        clean_content="需要深圳客户资源",
        msg_time_inferred=datetime(2026, 7, 2, 22, 30, 0),
        clean_time=datetime(2026, 7, 3, 9, 15, 0),
    )

    analysis = analyze_clean_group_message(clean, analyze_time=datetime(2026, 7, 3, 10, 0, 0))

    assert analysis.activity_date == date(2026, 7, 2)
    assert analysis.activity_hour == 22


def test_build_group_daily_report_uses_aggregate_only() -> None:
    stats = DailyReportStats(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        message_count=14,
        sender_count=5,
        demand_count=4,
        supply_count=2,
        contact_count=3,
        opportunity_count=2,
        peak_hour=9,
        top_keywords=[("深圳", 6), ("需要", 4)],
        top_regions=[("深圳", 6)],
        top_categories=[("兼职", 3)],
        top_opportunity_keywords=[("项目", 2)],
    )

    draft = build_group_daily_report(stats, generate_time=datetime(2026, 7, 3, 18, 0, 0))

    assert draft.title == "核心群A 2026-07-03 群日报草稿"
    assert draft.message_count == 14
    assert draft.sender_count == 5
    assert draft.demand_count == 4
    assert draft.supply_count == 2
    assert draft.contact_count == 3
    assert draft.opportunity_count == 2
    assert draft.peak_hour == 9
    assert draft.report_version == "v2"
    assert "## 核心指标" in draft.markdown_body
    assert "消息数：14" in draft.markdown_body
    assert "可疑商机数：2" in draft.markdown_body
    assert "联系方式标记占比：21.4%" in draft.markdown_body
    assert "## 地区命中 TOP" in draft.markdown_body
    assert "深圳：6" in draft.markdown_body
    assert "## 品类命中 TOP" in draft.markdown_body
    assert "兼职：3" in draft.markdown_body
    assert "## 商机词 TOP" in draft.markdown_body
    assert "项目：2" in draft.markdown_body
    assert "深圳：6" in draft.markdown_body
