from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class ArticleDailyReportStats:
    report_date: date
    account_name: str
    article_count: int
    avg_content_length: int
    top_tags: list[tuple[str, int]]
    top_keywords: list[tuple[str, int]]


@dataclass(frozen=True)
class ArticleDailyReportDraft:
    report_date: date
    account_name: str
    title: str
    markdown_body: str
    article_count: int
    avg_content_length: int
    top_tags: list[tuple[str, int]]
    top_keywords: list[tuple[str, int]]
    report_version: str
    generate_time: datetime

    def top_tags_json(self) -> str:
        return json.dumps([{"tag": tag, "count": count} for tag, count in self.top_tags], ensure_ascii=False)

    def top_keywords_json(self) -> str:
        return json.dumps(
            [{"keyword": keyword, "count": count} for keyword, count in self.top_keywords],
            ensure_ascii=False,
        )


def build_article_daily_report(
    stats: ArticleDailyReportStats,
    generate_time: datetime,
) -> ArticleDailyReportDraft:
    title = f"{stats.account_name} {stats.report_date.isoformat()} 文章日报草稿"
    tag_lines = _ranked_lines(stats.top_tags)
    keyword_lines = _ranked_lines(stats.top_keywords)
    body = "\n".join(
        [
            f"# {title}",
            "",
            "## 核心指标",
            f"- 文章数：{stats.article_count}",
            f"- 平均内容长度：{stats.avg_content_length}",
            "",
            "## 主题标签 TOP",
            tag_lines,
            "",
            "## 关键词 TOP",
            keyword_lines,
            "",
            "## 说明",
            "- 本日报基于 article analysis 结构化结果按规则生成。",
            "- 当前版本不调用外部 AI，不包含文章链接、HTML 或原文。",
        ]
    )

    return ArticleDailyReportDraft(
        report_date=stats.report_date,
        account_name=stats.account_name,
        title=title,
        markdown_body=body,
        article_count=stats.article_count,
        avg_content_length=stats.avg_content_length,
        top_tags=stats.top_tags,
        top_keywords=stats.top_keywords,
        report_version="v1",
        generate_time=generate_time,
    )


def _ranked_lines(items: list[tuple[str, int]]) -> str:
    if not items:
        return "- 暂无"
    return "\n".join(f"{index}. {label}：{count}" for index, (label, count) in enumerate(items, start=1))
