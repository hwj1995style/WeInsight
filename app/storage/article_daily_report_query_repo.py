from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.pipelines.article_daily_report_query_service import (
    ArticleDailyReportDetail,
    ArticleDailyReportSummary,
)
from app.domain.report_lifecycle import GenerationTrigger, ReportLifecycle, ReportStatus


_ZONE = ZoneInfo("Asia/Shanghai")


class MysqlArticleDailyReportQueryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_daily_reports(
        self,
        report_date: date,
        account_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[ArticleDailyReportSummary]:
        account_filter = "AND account_name = :account_name" if account_name else ""
        statement = text(
            f"""
            SELECT
                report_date,
                account_name,
                title,
                article_count,
                avg_content_length,
                generate_time,
                report_status,
                data_cutoff_time,
                generation_trigger,
                last_generated_by
            FROM wechat_article_daily_report
            WHERE report_date = :report_date
              {account_filter}
            ORDER BY report_date DESC, account_name ASC
            LIMIT :limit
            OFFSET :offset
            """
        )
        params = {
            "report_date": report_date,
            "account_name": account_name,
            "limit": limit,
            "offset": offset,
        }
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [self._summary_from_row(row) for row in rows]

    def get_daily_report(self, report_date: date, account_name: str) -> ArticleDailyReportDetail | None:
        statement = text(
            """
            SELECT
                report_date,
                account_name,
                title,
                markdown_body,
                article_count,
                avg_content_length,
                top_tags_json,
                top_keywords_json,
                report_version,
                generate_time,
                report_status,
                data_cutoff_time,
                generation_trigger,
                last_generated_by
            FROM wechat_article_daily_report
            WHERE report_date = :report_date
              AND account_name = :account_name
            LIMIT 1
            """
        )
        params = {"report_date": report_date, "account_name": account_name}
        with self.engine.begin() as connection:
            row = connection.execute(statement, params).mappings().first()
        if row is None:
            return None
        lifecycle = _lifecycle_from_row(row)
        return ArticleDailyReportDetail(
            report_date=row["report_date"],
            account_name=str(row["account_name"]),
            title=str(row["title"]),
            markdown_body=str(row["markdown_body"] or ""),
            article_count=int(row["article_count"] or 0),
            avg_content_length=int(row["avg_content_length"] or 0),
            top_tags_json=str(row["top_tags_json"] or "[]"),
            top_keywords_json=str(row["top_keywords_json"] or "[]"),
            report_version=str(row["report_version"] or "v1"),
            generate_time=row["generate_time"],
            report_status=lifecycle.report_status,
            data_cutoff_time=lifecycle.data_cutoff_time,
            generation_trigger=lifecycle.generation_trigger,
            last_generated_by=lifecycle.last_generated_by,
        )

    def count_daily_reports(self, report_date: date, account_name: str | None) -> int:
        account_filter = "AND account_name = :account_name" if account_name else ""
        statement = text(f"""
            SELECT COUNT(*) FROM wechat_article_daily_report
            WHERE report_date = :report_date {account_filter}
        """)
        with self.engine.begin() as connection:
            value = connection.execute(
                statement, {"report_date": report_date, "account_name": account_name}
            ).scalar_one()
        return int(value)

    def _summary_from_row(self, row) -> ArticleDailyReportSummary:
        lifecycle = _lifecycle_from_row(row)
        return ArticleDailyReportSummary(
            report_date=row["report_date"],
            account_name=str(row["account_name"]),
            title=str(row["title"]),
            article_count=int(row["article_count"] or 0),
            avg_content_length=int(row["avg_content_length"] or 0),
            generate_time=row["generate_time"],
            report_status=lifecycle.report_status,
            data_cutoff_time=lifecycle.data_cutoff_time,
            generation_trigger=lifecycle.generation_trigger,
            last_generated_by=lifecycle.last_generated_by,
        )


def _report_status(value: object) -> ReportStatus:
    try:
        return ReportStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid report_status: {value!r}") from exc


def _generation_trigger(value: object) -> GenerationTrigger:
    try:
        return GenerationTrigger(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid generation_trigger: {value!r}") from exc


def _data_cutoff_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"invalid data_cutoff_time: {value!r}")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


def _lifecycle_from_row(row) -> ReportLifecycle:
    return ReportLifecycle(
        report_status=_report_status(row["report_status"]),
        data_cutoff_time=_data_cutoff_time(row["data_cutoff_time"]),
        generation_trigger=_generation_trigger(row["generation_trigger"]),
        last_generated_by=row["last_generated_by"],
    )
