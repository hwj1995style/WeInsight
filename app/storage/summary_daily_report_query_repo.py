from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.pipelines.summary_daily_report_query_service import (
    SummaryArticleDailyReport,
    SummaryGroupDailyReport,
)


class MysqlSummaryDailyReportQueryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_group_reports(
        self, report_date: date, limit: int = 100, offset: int = 0
    ) -> list[SummaryGroupDailyReport]:
        statement = text(
            """
            SELECT
                report_date,
                group_name,
                title,
                message_count,
                sender_count,
                demand_count,
                supply_count,
                contact_count,
                peak_hour,
                generate_time
            FROM wechat_group_daily_report
            WHERE report_date = :report_date
            ORDER BY group_name ASC
            LIMIT :limit OFFSET :offset
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(
                statement,
                {"report_date": report_date, "limit": limit, "offset": offset},
            ).mappings().all()
        return [self._group_report_from_row(row) for row in rows]

    def list_article_reports(
        self, report_date: date, limit: int = 100, offset: int = 0
    ) -> list[SummaryArticleDailyReport]:
        statement = text(
            """
            SELECT
                report_date,
                account_name,
                title,
                article_count,
                avg_content_length,
                generate_time
            FROM wechat_article_daily_report
            WHERE report_date = :report_date
            ORDER BY account_name ASC
            LIMIT :limit OFFSET :offset
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(
                statement,
                {"report_date": report_date, "limit": limit, "offset": offset},
            ).mappings().all()
        return [self._article_report_from_row(row) for row in rows]

    def _group_report_from_row(self, row) -> SummaryGroupDailyReport:
        return SummaryGroupDailyReport(
            report_date=row["report_date"],
            group_name=str(row["group_name"]),
            title=str(row["title"]),
            message_count=int(row["message_count"] or 0),
            sender_count=int(row["sender_count"] or 0),
            demand_count=int(row["demand_count"] or 0),
            supply_count=int(row["supply_count"] or 0),
            contact_count=int(row["contact_count"] or 0),
            peak_hour=None if row["peak_hour"] is None else int(row["peak_hour"]),
            generate_time=row["generate_time"],
        )

    def _article_report_from_row(self, row) -> SummaryArticleDailyReport:
        return SummaryArticleDailyReport(
            report_date=row["report_date"],
            account_name=str(row["account_name"]),
            title=str(row["title"]),
            article_count=int(row["article_count"] or 0),
            avg_content_length=int(row["avg_content_length"] or 0),
            generate_time=row["generate_time"],
        )
