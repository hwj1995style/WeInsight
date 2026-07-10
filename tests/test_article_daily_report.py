from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.article_daily_report import ArticleDailyReportStats, build_article_daily_report
from app.domain.report_lifecycle import ReportLifecycle, ReportStatus
from app.pipelines.article_daily_report_service import ArticleDailyReportService


LIFECYCLE = ReportLifecycle.provisional(
    cutoff=datetime(2026, 7, 6, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    generated_by="admin",
)


def test_build_article_daily_report_uses_analysis_fields_only() -> None:
    report = build_article_daily_report(
        ArticleDailyReportStats(
            report_date=date(2026, 7, 6),
            account_name="行业观察",
            article_count=2,
            avg_content_length=1300,
            top_tags=[("深圳", 2), ("报价", 1)],
            top_keywords=[("供应链", 1)],
        ),
        generate_time=datetime(2026, 7, 6, 20, 0),
    )

    assert report.title == "行业观察 2026-07-06 文章日报草稿"
    assert report.article_count == 2
    assert report.avg_content_length == 1300
    assert report.report_version == "v1"
    assert "文章数：2" in report.markdown_body
    assert "平均内容长度：1300" in report.markdown_body
    assert "深圳：2" in report.markdown_body
    assert "供应链：1" in report.markdown_body
    assert "article_url" not in report.markdown_body
    assert "mp.weixin.qq.com" not in report.markdown_body
    assert "正文" not in report.markdown_body


def test_article_daily_report_service_generates_reports_and_marks_date_task_success() -> None:
    stats = ArticleDailyReportStats(
        report_date=date(2026, 7, 6),
        account_name="行业观察",
        article_count=2,
        avg_content_length=1300,
        top_tags=[("深圳", 2), ("报价", 1)],
        top_keywords=[("供应链", 1)],
    )
    repo = FakeArticleDailyReportRepo([stats])
    service = ArticleDailyReportService(repo=repo)

    result = service.generate_once(
        report_date=date(2026, 7, 6),
        account_name=None,
        generate_time=datetime(2026, 7, 6, 20, 0),
        lifecycle=LIFECYCLE,
    )

    assert result.report_date == date(2026, 7, 6)
    assert result.generated_count == 1
    assert repo.upserts[0].title == "行业观察 2026-07-06 文章日报草稿"
    assert repo.lifecycles[0].report_status is ReportStatus.PROVISIONAL
    assert repo.success_dates == [date(2026, 7, 6)]


def test_article_daily_report_service_does_not_mark_date_task_success_for_single_account() -> None:
    stats = ArticleDailyReportStats(
        report_date=date(2026, 7, 6),
        account_name="行业观察",
        article_count=1,
        avg_content_length=900,
        top_tags=[],
        top_keywords=[],
    )
    repo = FakeArticleDailyReportRepo([stats])
    service = ArticleDailyReportService(repo=repo)

    service.generate_once(
        report_date=date(2026, 7, 6),
        account_name="行业观察",
        generate_time=datetime(2026, 7, 6, 20, 0),
        lifecycle=LIFECYCLE,
    )

    assert repo.success_dates == []


class FakeArticleDailyReportRepo:
    def __init__(self, stats_rows: list[ArticleDailyReportStats]) -> None:
        self.stats_rows = stats_rows
        self.upserts = []
        self.lifecycles = []
        self.success_dates = []

    def list_daily_report_stats(self, report_date: date, account_name: str | None) -> list[ArticleDailyReportStats]:
        assert report_date == date(2026, 7, 6)
        if account_name is None:
            return self.stats_rows
        return [stats for stats in self.stats_rows if stats.account_name == account_name]

    def upsert_daily_report(self, report, lifecycle: ReportLifecycle) -> None:
        self.upserts.append(report)
        self.lifecycles.append(lifecycle)

    def mark_daily_report_task_success(self, report_date: date) -> None:
        self.success_dates.append(report_date)
