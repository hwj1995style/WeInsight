from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


def list_referencing_jobs_on_connection(
    connection: Connection,
    source_type: str,
    source_id: int,
    active_only: bool,
    lock_rows: bool = False,
) -> list[str]:
    statement = _referencing_jobs_statement(source_type, active_only, lock_rows)
    rows = connection.execute(statement, {"source_id": source_id}).mappings().all()
    return list(dict.fromkeys(str(row["job_name"]) for row in rows))


def has_group_history_on_connection(
    connection: Connection, group_name: str
) -> bool:
    result = connection.execute(
        _GROUP_HISTORY_STATEMENT, {"source_name": group_name}
    )
    return bool(result.scalar_one())


def has_article_history_on_connection(
    connection: Connection, account_name: str
) -> bool:
    result = connection.execute(
        _ARTICLE_HISTORY_STATEMENT, {"source_name": account_name}
    )
    return bool(result.scalar_one())


class MysqlSourceReferenceRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_referencing_jobs(
        self, source_type: str, source_id: int, active_only: bool
    ) -> list[str]:
        with self.engine.begin() as connection:
            return list_referencing_jobs_on_connection(
                connection, source_type, source_id, active_only
            )

    def has_group_history(self, group_name: str) -> bool:
        with self.engine.begin() as connection:
            return has_group_history_on_connection(connection, group_name)

    def has_article_history(self, account_name: str) -> bool:
        with self.engine.begin() as connection:
            return has_article_history_on_connection(connection, account_name)


def _referencing_jobs_statement(
    source_type: str, active_only: bool, lock_rows: bool = False
):
    if source_type == "group":
        source_predicate = "target.group_config_id = :source_id"
    elif source_type == "article":
        source_predicate = "target.article_config_id = :source_id"
    else:
        raise ValueError("source_type must be group or article")

    active_predicate = (
        "AND job.status IN ('scheduled', 'active', 'stop_requested')"
        if active_only
        else ""
    )
    lock_clause = "FOR SHARE" if lock_rows else ""
    return text(
        f"""
        SELECT
            job.job_name
        FROM wechat_collection_job_target target
        JOIN wechat_collection_job job
          ON job.id = target.job_id
        WHERE {source_predicate}
          {active_predicate}
        ORDER BY job.job_name ASC
        {lock_clause}
        """
    )


_GROUP_HISTORY_STATEMENT = text(
    """
    SELECT (
        EXISTS(
            SELECT 1 FROM wechat_group_msg_raw
            WHERE group_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_group_msg_clean
            WHERE group_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_group_msg_analysis
            WHERE group_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_group_daily_report
            WHERE group_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_group_collect_cursor
            WHERE group_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_group_collect_log
            WHERE source_name = :source_name LIMIT 1
        )
    ) AS has_history
    """
)


_ARTICLE_HISTORY_STATEMENT = text(
    """
    SELECT (
        EXISTS(
            SELECT 1 FROM wechat_article_raw
            WHERE account_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_article_clean
            WHERE account_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_article_analysis
            WHERE account_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_article_egg_price_item
            WHERE account_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_article_daily_report
            WHERE account_name = :source_name LIMIT 1
        )
        OR EXISTS(
            SELECT 1 FROM wechat_article_collect_log
            WHERE account_name = :source_name LIMIT 1
        )
    ) AS has_history
    """
)
