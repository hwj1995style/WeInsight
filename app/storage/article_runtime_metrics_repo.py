from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ArticleTaskBacklogSummary:
    task_type: str
    status: str
    count: int


@dataclass(frozen=True)
class ArticleRuntimeMetrics:
    window_hours: int
    account_total_count: int
    account_enabled_count: int
    collect_success_count: int
    collect_failed_count: int
    collect_skipped_count: int
    collect_total_count: int
    latest_error_summary: str | None
    task_backlogs: list[ArticleTaskBacklogSummary]


class MysqlArticleRuntimeMetricsRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_metrics(self, hours: int) -> ArticleRuntimeMetrics:
        if hours <= 0:
            raise ValueError("hours must be greater than 0")

        with self.engine.begin() as connection:
            account_row = connection.execute(_account_metrics_statement()).mappings().one()
            collect_row = connection.execute(_collect_metrics_statement(), {"hours": hours}).mappings().one()
            task_rows = connection.execute(_task_backlog_statement()).mappings().all()
            latest_error_row = (
                connection.execute(_latest_error_statement(), {"hours": hours}).mappings().first()
            )

        return ArticleRuntimeMetrics(
            window_hours=hours,
            account_total_count=int(account_row["account_total_count"] or 0),
            account_enabled_count=int(account_row["account_enabled_count"] or 0),
            collect_success_count=int(collect_row["collect_success_count"] or 0),
            collect_failed_count=int(collect_row["collect_failed_count"] or 0),
            collect_skipped_count=int(collect_row["collect_skipped_count"] or 0),
            collect_total_count=int(collect_row["collect_total_count"] or 0),
            latest_error_summary=_safe_error_summary(latest_error_row),
            task_backlogs=[
                ArticleTaskBacklogSummary(
                    task_type=str(row["task_type"]),
                    status=str(row["status"]),
                    count=int(row["cnt"]),
                )
                for row in task_rows
            ],
        )


def _account_metrics_statement():
    return text(
        """
        SELECT
            COUNT(*) AS account_total_count,
            COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS account_enabled_count
        FROM wechat_public_account_config
        """
    )


def _collect_metrics_statement():
    return text(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS collect_success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS collect_failed_count,
            COALESCE(SUM(CASE WHEN status IN ('skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS collect_skipped_count,
            COUNT(*) AS collect_total_count
        FROM wechat_article_collect_log
        WHERE start_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)
        """
    )


def _task_backlog_statement():
    return text(
        """
        SELECT
            task_type,
            status,
            COUNT(*) AS cnt
        FROM wechat_article_process_task
        WHERE status IN ('pending', 'running', 'failed')
          AND task_type <> 'article_daily_report'
        GROUP BY task_type, status
        ORDER BY task_type ASC, status ASC
        """
    )


def _latest_error_statement():
    return text(
        """
        SELECT
            CONCAT(
                COALESCE(error_code, status),
                '@',
                COALESCE(stage, ''),
                ': ',
                LEFT(COALESCE(error_msg, ''), 160)
            ) AS latest_error_summary
        FROM wechat_article_collect_log
        WHERE start_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)
          AND status IN ('failed', 'interrupted')
        ORDER BY id DESC
        LIMIT 1
        """
    )


def _safe_error_summary(row) -> str | None:
    if row is None:
        return None
    summary = str(row["latest_error_summary"] or "").strip()
    if not summary:
        return None
    summary = re.sub(r"https?://\S+", "[redacted-url]", summary)
    summary = re.sub(r"mp\.weixin\.qq\.com/\S+", "[redacted-url]", summary)
    summary = re.sub(r"\s+", " ", summary)
    return summary[:200]
