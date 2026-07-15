from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.pipelines.summary_daily_report_query_service import (
    SummaryArticleDailyReport,
    SummaryDailyReportSourceBundle,
    SummaryGroupDailyReport,
)


@dataclass(frozen=True)
class SummaryDailyReportDraft:
    report_date: date
    title: str
    markdown_body: str
    group_report_count: int
    article_report_count: int
    generate_time: datetime


def build_summary_daily_report(
    bundle: SummaryDailyReportSourceBundle,
    generate_time: datetime,
) -> SummaryDailyReportDraft:
    title = f"{bundle.report_date.isoformat()} 双链路汇总日报草稿"
    body = "\n".join(
        [
            f"# {title}",
            "",
            "## 总览",
            f"- 微信群日报数：{len(bundle.group_reports)}",
            f"- 公众号/订阅号日报数：{len(bundle.article_reports)}",
            f"- 生成时间：{_format_datetime(generate_time)}",
            "",
            "## 微信群日报",
            _group_report_lines(bundle.group_reports),
            "",
            "## 公众号/订阅号日报",
            _article_report_lines(bundle.article_reports),
            "",
            "## 隔离说明",
            "- 本汇总只使用已生成的群日报和文章日报摘要。",
            "- 本汇总不占用微信 UI，不修改群链路或公众号/订阅号链路状态。",
        ]
    )
    return SummaryDailyReportDraft(
        report_date=bundle.report_date,
        title=title,
        markdown_body=body,
        group_report_count=len(bundle.group_reports),
        article_report_count=len(bundle.article_reports),
        generate_time=generate_time,
    )


def _group_report_lines(reports: list[SummaryGroupDailyReport]) -> str:
    if not reports:
        return "- 暂无微信群日报"
    return "\n".join(
        [
            (
                f"{index}. {report.group_name}："
                f"消息数：{report.message_count}，"
                f"发送人数：{report.sender_count}，"
                f"需求：{report.demand_count}，"
                f"供应：{report.supply_count}，"
                f"联系方式：{report.contact_count}，"
                f"峰值小时：{_format_optional(report.peak_hour)}"
            )
            for index, report in enumerate(reports, start=1)
        ]
    )


def _article_report_lines(reports: list[SummaryArticleDailyReport]) -> str:
    if not reports:
        return "- 暂无公众号/订阅号日报"
    return "\n".join(
        [
            (
                f"{index}. {report.account_name}："
                f"文章数：{report.article_count}，"
                f"平均内容长度：{report.avg_content_length}"
            )
            for index, report in enumerate(reports, start=1)
        ]
    )


def _format_optional(value) -> str:
    return "-" if value is None else str(value)


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
