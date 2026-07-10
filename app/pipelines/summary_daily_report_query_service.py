from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class SummaryGroupDailyReport:
    report_date: date
    group_name: str
    title: str
    message_count: int
    sender_count: int
    demand_count: int
    supply_count: int
    contact_count: int
    peak_hour: int | None
    generate_time: datetime


@dataclass(frozen=True)
class SummaryArticleDailyReport:
    report_date: date
    account_name: str
    title: str
    article_count: int
    avg_content_length: int
    generate_time: datetime


@dataclass(frozen=True)
class SummaryDailyReportSourceBundle:
    report_date: date
    group_reports: list[SummaryGroupDailyReport]
    article_reports: list[SummaryArticleDailyReport]


class SummaryDailyReportQueryRepo(Protocol):
    def list_group_reports(
        self, report_date: date, limit: int = 100, offset: int = 0
    ) -> list[SummaryGroupDailyReport]:
        ...

    def list_article_reports(
        self, report_date: date, limit: int = 100, offset: int = 0
    ) -> list[SummaryArticleDailyReport]:
        ...


class SummaryDailyReportQueryService:
    def __init__(self, *, repo: SummaryDailyReportQueryRepo) -> None:
        self.repo = repo

    def load_sources(
        self,
        report_date: date,
        limit: int | None = None,
        offset: int = 0,
    ) -> SummaryDailyReportSourceBundle:
        if limit is None and offset == 0:
            group_reports = self.repo.list_group_reports(report_date)
            article_reports = self.repo.list_article_reports(report_date)
        else:
            bounded_limit = 100 if limit is None else limit
            group_reports = self.repo.list_group_reports(
                report_date, bounded_limit, offset
            )
            article_reports = self.repo.list_article_reports(
                report_date, bounded_limit, offset
            )
        return SummaryDailyReportSourceBundle(
            report_date=report_date,
            group_reports=group_reports,
            article_reports=article_reports,
        )
