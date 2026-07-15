from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.group_analysis_rules import AnalysisRuleSet, DEFAULT_ANALYSIS_RULE_SET
from app.domain.group_cleaning import CleanGroupMessage


@dataclass(frozen=True)
class AnalyzedGroupMessage:
    msg_hash: str
    group_name: str
    sender_hash: str | None
    msg_time_display: str
    msg_time_inferred: datetime | None
    activity_date: date
    activity_hour: int
    intent_type: str
    keyword_hits: list[str]
    region_hits: list[str]
    category_hits: list[str]
    opportunity_hits: list[str]
    opportunity_score: int
    has_contact: bool
    content_length: int
    analysis_version: str
    analyze_time: datetime


@dataclass(frozen=True)
class DailyReportStats:
    report_date: date
    group_name: str
    message_count: int
    sender_count: int
    demand_count: int
    supply_count: int
    contact_count: int
    opportunity_count: int
    peak_hour: int | None
    top_keywords: list[tuple[str, int]]
    top_regions: list[tuple[str, int]]
    top_categories: list[tuple[str, int]]
    top_opportunity_keywords: list[tuple[str, int]]


@dataclass(frozen=True)
class DailyReportDraft:
    report_date: date
    group_name: str
    title: str
    markdown_body: str
    message_count: int
    sender_count: int
    demand_count: int
    supply_count: int
    contact_count: int
    opportunity_count: int
    peak_hour: int | None
    top_keywords: list[tuple[str, int]]
    top_regions: list[tuple[str, int]]
    top_categories: list[tuple[str, int]]
    top_opportunity_keywords: list[tuple[str, int]]
    report_version: str
    generate_time: datetime

    def top_keywords_json(self) -> str:
        return json.dumps(
            [{"keyword": keyword, "count": count} for keyword, count in self.top_keywords],
            ensure_ascii=False,
        )


def analyze_clean_group_message(
    message: CleanGroupMessage,
    analyze_time: datetime,
    rule_set: AnalysisRuleSet | None = None,
) -> AnalyzedGroupMessage:
    active_rule_set = rule_set or DEFAULT_ANALYSIS_RULE_SET
    event_time = message.msg_time_inferred or message.clean_time
    keyword_hits = _keyword_hits(message.clean_content, active_rule_set.tracked_keywords)
    region_hits = _keyword_hits(message.clean_content, active_rule_set.region_keywords)
    category_hits = _keyword_hits(message.clean_content, active_rule_set.category_keywords)
    opportunity_hits = _keyword_hits(message.clean_content, active_rule_set.opportunity_keywords)
    intent_type = _intent_type(message, keyword_hits, active_rule_set)
    has_contact = message.has_phone or message.has_wechat_id

    return AnalyzedGroupMessage(
        msg_hash=message.msg_hash,
        group_name=message.group_name,
        sender_hash=message.sender_hash,
        msg_time_display=message.msg_time_display,
        msg_time_inferred=message.msg_time_inferred,
        activity_date=event_time.date(),
        activity_hour=event_time.hour,
        intent_type=intent_type,
        keyword_hits=keyword_hits,
        region_hits=region_hits,
        category_hits=category_hits,
        opportunity_hits=opportunity_hits,
        opportunity_score=_opportunity_score(
            intent_type=intent_type,
            has_contact=has_contact,
            region_hits=region_hits,
            category_hits=category_hits,
            opportunity_hits=opportunity_hits,
        ),
        has_contact=has_contact,
        content_length=message.content_length,
        analysis_version=active_rule_set.version,
        analyze_time=analyze_time,
    )


def build_group_daily_report(stats: DailyReportStats, generate_time: datetime) -> DailyReportDraft:
    title = f"{stats.group_name} {stats.report_date.isoformat()} 群日报草稿"
    peak_hour_text = "" if stats.peak_hour is None else f"{stats.peak_hour:02d}:00"
    keyword_lines = _keyword_lines(stats.top_keywords)
    region_lines = _keyword_lines(stats.top_regions)
    category_lines = _keyword_lines(stats.top_categories)
    opportunity_lines = _keyword_lines(stats.top_opportunity_keywords)
    contact_rate = _percent(stats.contact_count, stats.message_count)
    opportunity_rate = _percent(stats.opportunity_count, stats.message_count)
    body = "\n".join(
        [
            f"# {title}",
            "",
            "## 核心指标",
            f"- 消息数：{stats.message_count}",
            f"- 活跃发送人数：{stats.sender_count}",
            f"- 需求消息数：{stats.demand_count}",
            f"- 供应消息数：{stats.supply_count}",
            f"- 联系方式标记数：{stats.contact_count}",
            f"- 高峰小时：{peak_hour_text}",
            "",
            "## 商机概览",
            f"- 可疑商机数：{stats.opportunity_count}",
            f"- 可疑商机占比：{opportunity_rate}",
            f"- 联系方式标记数：{stats.contact_count}",
            f"- 联系方式标记占比：{contact_rate}",
            "",
            "## 高频关键词",
            keyword_lines,
            "",
            "## 地区命中 TOP",
            region_lines,
            "",
            "## 品类命中 TOP",
            category_lines,
            "",
            "## 商机词 TOP",
            opportunity_lines,
            "",
            "## 说明",
            "- 本日报基于脱敏后的 analysis 结构化结果按规则生成。",
            "- 当前版本不调用外部 AI，不包含 raw 原文。",
        ]
    )

    return DailyReportDraft(
        report_date=stats.report_date,
        group_name=stats.group_name,
        title=title,
        markdown_body=body,
        message_count=stats.message_count,
        sender_count=stats.sender_count,
        demand_count=stats.demand_count,
        supply_count=stats.supply_count,
        contact_count=stats.contact_count,
        opportunity_count=stats.opportunity_count,
        peak_hour=stats.peak_hour,
        top_keywords=stats.top_keywords,
        top_regions=stats.top_regions,
        top_categories=stats.top_categories,
        top_opportunity_keywords=stats.top_opportunity_keywords,
        report_version="v2",
        generate_time=generate_time,
    )


def _keyword_hits(content: str, tracked_keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in tracked_keywords if keyword in content]


def _intent_type(message: CleanGroupMessage, keyword_hits: list[str], rule_set: AnalysisRuleSet) -> str:
    if message.is_empty or not message.clean_content.strip():
        return "empty"
    demand_score = sum(1 for keyword in rule_set.demand_keywords if keyword in keyword_hits)
    supply_score = sum(1 for keyword in rule_set.supply_keywords if keyword in keyword_hits)
    if demand_score > supply_score:
        return "demand"
    if supply_score > demand_score:
        return "supply"
    return "neutral"


def _opportunity_score(
    *,
    intent_type: str,
    has_contact: bool,
    region_hits: list[str],
    category_hits: list[str],
    opportunity_hits: list[str],
) -> int:
    score = 0
    if intent_type in {"demand", "supply"}:
        score += 1
    if has_contact:
        score += 1
    if region_hits:
        score += 1
    if category_hits:
        score += 1
    if opportunity_hits:
        score += 1
    return score


def _keyword_lines(top_keywords: list[tuple[str, int]]) -> str:
    if not top_keywords:
        return "- 暂无"
    return "\n".join(f"{index}. {keyword}：{count}" for index, (keyword, count) in enumerate(top_keywords, start=1))


def _percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0%"
    return f"{numerator / denominator * 100:.1f}%"
