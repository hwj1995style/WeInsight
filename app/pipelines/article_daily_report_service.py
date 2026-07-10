from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.domain.article_daily_report import (
    ArticleDailyReportDraft,
    ArticleDailyReportStats,
    build_article_daily_report,
)


@dataclass(frozen=True)
class ArticleDailyReportResult:
    report_date: date
    generated_count: int


class ArticleDailyReportRepo(Protocol):
    def list_daily_report_stats(self, report_date: date, account_name: str | None) -> list[ArticleDailyReportStats]:
        ...

    def upsert_daily_report(self, report: ArticleDailyReportDraft) -> None:
        ...

    def mark_daily_report_task_success(self, report_date: date) -> None:
        ...


class ArticleDailyReportService:
    def __init__(self, *, repo: ArticleDailyReportRepo) -> None:
        self.repo = repo

    def generate_once(
        self,
        *,
        report_date: date,
        account_name: str | None,
        generate_time: datetime,
    ) -> ArticleDailyReportResult:
        stats_rows = self.repo.list_daily_report_stats(report_date=report_date, account_name=account_name)
        for stats in stats_rows:
            report = build_article_daily_report(stats, generate_time=generate_time)
            self.repo.upsert_daily_report(report)
        if account_name is None:
            self.repo.mark_daily_report_task_success(report_date)
        return ArticleDailyReportResult(report_date=report_date, generated_count=len(stats_rows))
