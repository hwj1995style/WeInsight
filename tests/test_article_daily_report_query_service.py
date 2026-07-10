from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.report_lifecycle import GenerationTrigger, ReportStatus
from app.pipelines.article_daily_report_query_service import (
    ArticleDailyReportDetail,
    ArticleDailyReportNotFoundError,
    ArticleDailyReportQueryService,
    ArticleDailyReportSummary,
)


class FakeArticleDailyReportQueryRepo:
    def __init__(self, detail: ArticleDailyReportDetail | None = None) -> None:
        self.detail = detail
        self.list_calls: list[tuple[date, str | None, int]] = []
        self.get_calls: list[tuple[date, str]] = []

    def list_daily_reports(
        self,
        report_date: date,
        account_name: str | None,
        limit: int,
    ) -> list[ArticleDailyReportSummary]:
        self.list_calls.append((report_date, account_name, limit))
        return [
            ArticleDailyReportSummary(
                report_date=report_date,
                account_name="行业观察",
                title="行业观察 2026-07-06 文章日报草稿",
                article_count=2,
                avg_content_length=1300,
                generate_time=datetime(2026, 7, 6, 20, 0),
                report_status=ReportStatus.FINAL,
                data_cutoff_time=datetime(2026, 7, 7, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
                generation_trigger=GenerationTrigger.COMPENSATION,
                last_generated_by="system",
            )
        ]

    def get_daily_report(self, report_date: date, account_name: str) -> ArticleDailyReportDetail | None:
        self.get_calls.append((report_date, account_name))
        return self.detail


def _detail() -> ArticleDailyReportDetail:
    return ArticleDailyReportDetail(
        report_date=date(2026, 7, 6),
        account_name="行业观察",
        title="行业观察 2026-07-06 文章日报草稿",
        markdown_body="# 行业观察 2026-07-06 文章日报草稿\n\n## 核心指标\n- 文章数：2\n",
        article_count=2,
        avg_content_length=1300,
        top_tags_json='[{"tag":"深圳","count":2}]',
        top_keywords_json='[{"keyword":"供应链","count":2}]',
        report_version="v1",
        generate_time=datetime(2026, 7, 6, 20, 0),
        report_status=ReportStatus.FINAL,
        data_cutoff_time=datetime(2026, 7, 7, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        generation_trigger=GenerationTrigger.COMPENSATION,
        last_generated_by="system",
    )


def test_article_daily_report_query_service_lists_summaries() -> None:
    repo = FakeArticleDailyReportQueryRepo()
    service = ArticleDailyReportQueryService(repo=repo)

    reports = service.list_reports(report_date=date(2026, 7, 6), account_name=None, limit=10)

    assert len(reports) == 1
    assert reports[0].account_name == "行业观察"
    assert reports[0].article_count == 2
    assert reports[0].report_status is ReportStatus.FINAL
    assert repo.list_calls == [(date(2026, 7, 6), None, 10)]


def test_article_daily_report_query_service_gets_detail() -> None:
    repo = FakeArticleDailyReportQueryRepo(detail=_detail())
    service = ArticleDailyReportQueryService(repo=repo)

    report = service.get_report(report_date=date(2026, 7, 6), account_name="行业观察")

    assert report is not None
    assert report.markdown_body.startswith("# 行业观察")
    assert report.generation_trigger is GenerationTrigger.COMPENSATION
    assert repo.get_calls == [(date(2026, 7, 6), "行业观察")]


def test_article_daily_report_query_service_exports_markdown_to_default_file(tmp_path) -> None:
    repo = FakeArticleDailyReportQueryRepo(detail=_detail())
    service = ArticleDailyReportQueryService(repo=repo, export_root=tmp_path)

    result = service.export_report(report_date=date(2026, 7, 6), account_name="行业观察")

    assert result.export_path == tmp_path / "2026-07-06" / "行业观察.md"
    assert result.export_path.read_text(encoding="utf-8").startswith("# 行业观察")
    assert result.bytes_written > 0


def test_article_daily_report_query_service_raises_when_export_target_missing(tmp_path) -> None:
    repo = FakeArticleDailyReportQueryRepo(detail=None)
    service = ArticleDailyReportQueryService(repo=repo, export_root=tmp_path)

    with pytest.raises(ArticleDailyReportNotFoundError):
        service.export_report(report_date=date(2026, 7, 6), account_name="行业观察")
