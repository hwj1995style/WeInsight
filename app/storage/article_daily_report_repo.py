from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.article_daily_report import ArticleDailyReportDraft, ArticleDailyReportStats


class MysqlArticleDailyReportRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_daily_report_stats(self, report_date: date, account_name: str | None) -> list[ArticleDailyReportStats]:
        account_filter = "AND account_name = :account_name" if account_name else ""
        statement = text(
            f"""
            SELECT
                account_name,
                content_length,
                topic_tags_json,
                keyword_hits_json
            FROM wechat_article_analysis
            WHERE COALESCE(quote_date, publish_date) = :report_date
              {account_filter}
            ORDER BY account_name ASC, article_hash ASC
            """
        )
        params = {"report_date": report_date, "account_name": account_name}
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()

        return self._stats_from_rows(report_date, rows)

    def upsert_daily_report(self, report: ArticleDailyReportDraft) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_daily_report (
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
            ) VALUES (
                :report_date,
                :account_name,
                :title,
                :markdown_body,
                :article_count,
                :avg_content_length,
                :top_tags_json,
                :top_keywords_json,
                :report_version,
                :generate_time
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                markdown_body = VALUES(markdown_body),
                article_count = VALUES(article_count),
                avg_content_length = VALUES(avg_content_length),
                top_tags_json = VALUES(top_tags_json),
                top_keywords_json = VALUES(top_keywords_json),
                report_version = VALUES(report_version),
                generate_time = VALUES(generate_time),
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "report_date": report.report_date,
            "account_name": report.account_name,
            "title": report.title,
            "markdown_body": report.markdown_body,
            "article_count": report.article_count,
            "avg_content_length": report.avg_content_length,
            "top_tags_json": report.top_tags_json(),
            "top_keywords_json": report.top_keywords_json(),
            "report_version": report.report_version,
            "generate_time": report.generate_time,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def mark_daily_report_task_success(self, report_date: date) -> None:
        statement = text(
            """
            UPDATE wechat_article_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'article_daily_report'
              AND ref_type = 'date'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": report_date.isoformat()})

    def _stats_from_rows(self, report_date: date, rows) -> list[ArticleDailyReportStats]:
        grouped: dict[str, list] = defaultdict(list)
        for row in rows:
            grouped[str(row["account_name"])].append(row)

        stats: list[ArticleDailyReportStats] = []
        for account_name, account_rows in grouped.items():
            tag_counts: Counter[str] = Counter()
            keyword_counts: Counter[str] = Counter()
            total_content_length = 0
            for row in account_rows:
                total_content_length += int(row["content_length"] or 0)
                tag_counts.update(_load_json_list(row["topic_tags_json"]))
                keyword_counts.update(_load_json_list(row["keyword_hits_json"]))

            article_count = len(account_rows)
            avg_content_length = 0 if article_count == 0 else int(total_content_length / article_count)
            stats.append(
                ArticleDailyReportStats(
                    report_date=report_date,
                    account_name=account_name,
                    article_count=article_count,
                    avg_content_length=avg_content_length,
                    top_tags=tag_counts.most_common(10),
                    top_keywords=keyword_counts.most_common(10),
                )
            )

        return stats


def _load_json_list(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]
