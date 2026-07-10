from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.pipelines.article_daily_report_query_service import (
    ArticleDailyReportDetail,
    ArticleDailyReportSummary,
)


class MysqlArticleDailyReportQueryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_daily_reports(
        self,
        report_date: date,
        account_name: str | None,
        limit: int,
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
                generate_time
            FROM wechat_article_daily_report
            WHERE report_date = :report_date
              {account_filter}
            ORDER BY report_date DESC, account_name ASC
            LIMIT :limit
            """
        )
        params = {"report_date": report_date, "account_name": account_name, "limit": limit}
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
                generate_time
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
        )

    def _summary_from_row(self, row) -> ArticleDailyReportSummary:
        return ArticleDailyReportSummary(
            report_date=row["report_date"],
            account_name=str(row["account_name"]),
            title=str(row["title"]),
            article_count=int(row["article_count"] or 0),
            avg_content_length=int(row["avg_content_length"] or 0),
            generate_time=row["generate_time"],
        )
