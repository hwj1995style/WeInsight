from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.dashboard_service import (
    BacklogCount,
    CollectionOutcomeCounts,
    DashboardSnapshot,
)


class MysqlDashboardRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_snapshot(self, hours: int) -> DashboardSnapshot:
        with self.engine.begin() as connection:
            group_row = connection.execute(
                _group_collection_statement(), {"hours": hours}
            ).mappings().one()
            article_row = connection.execute(
                _article_collection_statement(), {"hours": hours}
            ).mappings().one()
            config_row = connection.execute(
                _config_count_statement()
            ).mappings().one()
            report_row = connection.execute(
                _report_count_statement(), {"hours": hours}
            ).mappings().one()
            backlog_rows = connection.execute(
                _backlog_statement()
            ).mappings().all()
        return DashboardSnapshot(
            window_hours=hours,
            group_collection=_outcomes(group_row),
            article_collection=_outcomes(article_row),
            group_config_total=int(group_row_value(config_row, "group_total")),
            group_config_enabled=int(group_row_value(config_row, "group_enabled")),
            article_config_total=int(group_row_value(config_row, "article_total")),
            article_config_enabled=int(group_row_value(config_row, "article_enabled")),
            group_daily_report_count=int(
                group_row_value(report_row, "group_report_count")
            ),
            article_daily_report_count=int(
                group_row_value(report_row, "article_report_count")
            ),
            backlogs=tuple(
                BacklogCount(
                    pipeline=str(row["pipeline"]),
                    task_type=str(row["task_type"]),
                    status=str(row["status"]),
                    count=int(row["count"] or 0),
                )
                for row in backlog_rows
            ),
        )


def _outcomes(row) -> CollectionOutcomeCounts:
    return CollectionOutcomeCounts(
        success=int(group_row_value(row, "success_count")),
        failed=int(group_row_value(row, "failed_count")),
        skipped=int(group_row_value(row, "skipped_count")),
        total=int(group_row_value(row, "total_count")),
    )


def group_row_value(row, key: str):
    return row[key] or 0


def _group_collection_statement():
    return _collection_statement("wechat_group_collect_log")


def _article_collection_statement():
    return _collection_statement("wechat_article_collect_log")


def _collection_statement(table_name: str):
    return text(
        f"""
        SELECT
            {_terminal_outcome_projection()}
        FROM {table_name}
        WHERE start_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)
        """
    )


def _terminal_outcome_projection() -> str:
    return """
            COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
            COALESCE(SUM(CASE WHEN status IN ('skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS skipped_count,
            COALESCE(SUM(CASE WHEN status IN ('success', 'failed', 'skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS total_count
    """


def _config_count_statement():
    return text(
        """
        SELECT
            (SELECT COUNT(*) FROM wechat_group_config) AS group_total,
            (SELECT COUNT(*) FROM wechat_group_config WHERE enabled = 1) AS group_enabled,
            (SELECT COUNT(*) FROM wechat_public_account_config) AS article_total,
            (SELECT COUNT(*) FROM wechat_public_account_config WHERE enabled = 1) AS article_enabled
        """
    )


def _report_count_statement():
    return text(
        """
        SELECT
            (SELECT COUNT(*) FROM wechat_group_daily_report
             WHERE generate_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)) AS group_report_count,
            (SELECT COUNT(*) FROM wechat_article_daily_report
             WHERE generate_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)) AS article_report_count
        """
    )


def _backlog_statement():
    return text(
        """
        SELECT pipeline, task_type, status, SUM(item_count) AS count
        FROM (
            SELECT 'group' AS pipeline, task_type, status, COUNT(*) AS item_count
            FROM wechat_group_process_task
            WHERE status IN ('pending', 'running', 'failed')
            GROUP BY task_type, status
            UNION ALL
            SELECT 'article' AS pipeline, task_type, status, COUNT(*) AS item_count
            FROM wechat_article_process_task
            WHERE status IN ('pending', 'running', 'failed')
            GROUP BY task_type, status
        ) AS backlog
        GROUP BY pipeline, task_type, status
        ORDER BY pipeline ASC, task_type ASC, status ASC
        """
    )
