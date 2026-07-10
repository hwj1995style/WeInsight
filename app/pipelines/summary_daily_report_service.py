from __future__ import annotations

from datetime import date, datetime

from app.domain.summary_daily_report import SummaryDailyReportDraft, build_summary_daily_report
from app.pipelines.summary_daily_report_query_service import SummaryDailyReportQueryService


class SummaryDailyReportService:
    def __init__(self, *, query_service: SummaryDailyReportQueryService) -> None:
        self.query_service = query_service

    def generate(self, report_date: date, generate_time: datetime) -> SummaryDailyReportDraft:
        bundle = self.query_service.load_sources(report_date)
        return build_summary_daily_report(bundle, generate_time=generate_time)
