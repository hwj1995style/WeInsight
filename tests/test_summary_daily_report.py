from __future__ import annotations

from datetime import date, datetime

from app.domain.summary_daily_report import build_summary_daily_report
from app.pipelines.summary_daily_report_query_service import (
    SummaryArticleDailyReport,
    SummaryDailyReportSourceBundle,
    SummaryGroupDailyReport,
)
from app.pipelines.summary_daily_report_service import SummaryDailyReportService


def _bundle() -> SummaryDailyReportSourceBundle:
    return SummaryDailyReportSourceBundle(
        report_date=date(2026, 7, 6),
        group_reports=[
            SummaryGroupDailyReport(
                report_date=date(2026, 7, 6),
                group_name="核心群A",
                title="核心群A 2026-07-06 群日报草稿",
                message_count=14,
                sender_count=7,
                demand_count=1,
                supply_count=2,
                contact_count=0,
                peak_hour=10,
                generate_time=datetime(2026, 7, 6, 18, 0),
            )
        ],
        article_reports=[
            SummaryArticleDailyReport(
                report_date=date(2026, 7, 6),
                account_name="行业观察",
                title="行业观察 2026-07-06 文章日报草稿",
                article_count=2,
                avg_content_length=1300,
                generate_time=datetime(2026, 7, 6, 20, 0),
            )
        ],
    )


def test_build_summary_daily_report_uses_only_report_metadata() -> None:
    draft = build_summary_daily_report(_bundle(), generate_time=datetime(2026, 7, 6, 21, 0))

    assert draft.title == "2026-07-06 双链路汇总日报草稿"
    assert draft.report_date == date(2026, 7, 6)
    assert draft.group_report_count == 1
    assert draft.article_report_count == 1
    assert draft.generate_time == datetime(2026, 7, 6, 21, 0)
    assert draft.markdown_body.startswith("# 2026-07-06 双链路汇总日报草稿")
    for section in ["## 总览", "## 微信群日报", "## 公众号/订阅号日报", "## 隔离说明"]:
        assert section in draft.markdown_body
    assert "核心群A" in draft.markdown_body
    assert "行业观察" in draft.markdown_body
    assert "消息数：14" in draft.markdown_body
    assert "文章数：2" in draft.markdown_body
    assert "wechat_group_process_task" not in draft.markdown_body
    assert "wechat_article_process_task" not in draft.markdown_body
    assert "wechat_group_msg_raw" not in draft.markdown_body
    assert "wechat_article_raw" not in draft.markdown_body
    assert "markdown_body" not in draft.markdown_body
    assert "article_url" not in draft.markdown_body
    assert "mp.weixin.qq.com" not in draft.markdown_body


def test_build_summary_daily_report_handles_empty_sources() -> None:
    bundle = SummaryDailyReportSourceBundle(
        report_date=date(2026, 7, 6),
        group_reports=[],
        article_reports=[],
    )

    draft = build_summary_daily_report(bundle, generate_time=datetime(2026, 7, 6, 21, 0))

    assert draft.group_report_count == 0
    assert draft.article_report_count == 0
    assert "暂无微信群日报" in draft.markdown_body
    assert "暂无公众号/订阅号日报" in draft.markdown_body


class FakeQueryService:
    def __init__(self) -> None:
        self.calls: list[date] = []

    def load_sources(self, report_date: date) -> SummaryDailyReportSourceBundle:
        self.calls.append(report_date)
        return _bundle()


def test_summary_daily_report_service_generates_draft() -> None:
    query_service = FakeQueryService()
    service = SummaryDailyReportService(query_service=query_service)

    draft = service.generate(report_date=date(2026, 7, 6), generate_time=datetime(2026, 7, 6, 21, 0))

    assert draft.markdown_body.startswith("# 2026-07-06 双链路汇总日报草稿")
    assert draft.group_report_count == 1
    assert draft.article_report_count == 1
    assert query_service.calls == [date(2026, 7, 6)]
