from __future__ import annotations

from datetime import date, datetime

from app.pipelines.summary_daily_report_query_service import (
    SummaryArticleDailyReport,
    SummaryDailyReportQueryService,
    SummaryGroupDailyReport,
)


class FakeSummaryQueryRepo:
    def __init__(self) -> None:
        self.group_calls: list[date] = []
        self.article_calls: list[date] = []

    def list_group_reports(self, report_date: date) -> list[SummaryGroupDailyReport]:
        self.group_calls.append(report_date)
        return [
            SummaryGroupDailyReport(
                report_date=report_date,
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
        ]

    def list_article_reports(self, report_date: date) -> list[SummaryArticleDailyReport]:
        self.article_calls.append(report_date)
        return [
            SummaryArticleDailyReport(
                report_date=report_date,
                account_name="行业观察",
                title="行业观察 2026-07-06 文章日报草稿",
                article_count=2,
                avg_content_length=1300,
                generate_time=datetime(2026, 7, 6, 20, 0),
            )
        ]


def test_summary_daily_report_query_service_loads_sources_from_two_report_tables() -> None:
    repo = FakeSummaryQueryRepo()
    service = SummaryDailyReportQueryService(repo=repo)

    bundle = service.load_sources(report_date=date(2026, 7, 6))

    assert bundle.report_date == date(2026, 7, 6)
    assert len(bundle.group_reports) == 1
    assert len(bundle.article_reports) == 1
    assert bundle.group_reports[0].group_name == "核心群A"
    assert bundle.article_reports[0].account_name == "行业观察"
    assert repo.group_calls == [date(2026, 7, 6)]
    assert repo.article_calls == [date(2026, 7, 6)]
