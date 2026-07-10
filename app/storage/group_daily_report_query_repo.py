from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.group_reports import DailyReportDetail, DailyReportSummary


class MysqlGroupDailyReportQueryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_daily_reports(
        self,
        report_date: date,
        group_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[DailyReportSummary]:
        group_filter = "AND group_name = :group_name" if group_name else ""
        statement = text(
            f"""
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
              {group_filter}
            ORDER BY report_date DESC, group_name ASC
            LIMIT :limit
            OFFSET :offset
            """
        )
        params = {
            "report_date": report_date,
            "group_name": group_name,
            "limit": limit,
            "offset": offset,
        }
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [self._summary_from_row(row) for row in rows]

    def get_daily_report(self, report_date: date, group_name: str) -> DailyReportDetail | None:
        statement = text(
            """
            SELECT
                report_date,
                group_name,
                title,
                markdown_body,
                message_count,
                sender_count,
                demand_count,
                supply_count,
                contact_count,
                peak_hour,
                top_keywords,
                report_version,
                generate_time
            FROM wechat_group_daily_report
            WHERE report_date = :report_date
              AND group_name = :group_name
            LIMIT 1
            """
        )
        params = {"report_date": report_date, "group_name": group_name}
        with self.engine.begin() as connection:
            row = connection.execute(statement, params).mappings().first()
        if row is None:
            return None
        return DailyReportDetail(
            report_date=row["report_date"],
            group_name=str(row["group_name"]),
            title=str(row["title"]),
            markdown_body=str(row["markdown_body"] or ""),
            message_count=int(row["message_count"] or 0),
            sender_count=int(row["sender_count"] or 0),
            demand_count=int(row["demand_count"] or 0),
            supply_count=int(row["supply_count"] or 0),
            contact_count=int(row["contact_count"] or 0),
            peak_hour=None if row["peak_hour"] is None else int(row["peak_hour"]),
            top_keywords=str(row["top_keywords"] or "[]"),
            report_version=str(row["report_version"] or "v1"),
            generate_time=row["generate_time"],
        )

    def _summary_from_row(self, row) -> DailyReportSummary:
        return DailyReportSummary(
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
