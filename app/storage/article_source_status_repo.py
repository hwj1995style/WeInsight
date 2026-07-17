from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class ArticleSourceStatusRecord:
    source_id: int
    account_name: str
    werss_source_id: str | None
    collection_enabled: bool
    downstream_processing_enabled: bool
    upstream_status: str
    upstream_last_seen_at: datetime | None
    last_article_time: datetime | None
    last_success_collect_time: datetime | None
    article_count: int
    pending_parse_count: int
    pending_analyze_count: int
    failed_count: int
    last_collect_status: str | None
    last_error: str | None
    updated_at: datetime | None
    latest_collect_log_time: datetime | None


class MysqlArticleSourceStatusRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_status_page(self, *, limit: int, offset: int) -> list[ArticleSourceStatusRecord]:
        with self.engine.begin() as connection:
            rows = connection.execute(_LIST_STATUS_SQL, {"limit": limit, "offset": offset}).mappings().all()
        return [ArticleSourceStatusRecord(
            source_id=int(row["source_id"]),
            account_name=str(row["account_name"]),
            werss_source_id=row["werss_source_id"],
            collection_enabled=bool(row["collection_enabled"]),
            downstream_processing_enabled=bool(row["downstream_processing_enabled"]),
            upstream_status=str(row["upstream_status"]),
            upstream_last_seen_at=row["upstream_last_seen_at"],
            last_article_time=row["last_article_time"],
            last_success_collect_time=row["last_success_collect_time"],
            article_count=int(row["article_count"] or 0),
            pending_parse_count=int(row["pending_parse_count"] or 0),
            pending_analyze_count=int(row["pending_analyze_count"] or 0),
            failed_count=int(row["failed_count"] or 0),
            last_collect_status=row["last_collect_status"],
            last_error=row["last_error"],
            updated_at=row["updated_at"],
            latest_collect_log_time=row["latest_collect_log_time"],
        ) for row in rows]

    def count_status_sources(self) -> int:
        with self.engine.begin() as connection:
            value = connection.execute(_COUNT_STATUS_SQL).scalar_one()
        return int(value)


# Every one-to-many table is reduced to one row per account before joining.
_COUNT_STATUS_SQL = text("""
SELECT COUNT(*)
FROM wechat_public_account_config
WHERE werss_source_id IS NOT NULL
  AND upstream_status IN ('active', 'disabled')
""")


_LIST_STATUS_SQL = text("""
WITH raw_stats AS (
    SELECT account_name, COUNT(*) AS article_count,
           MAX(publish_time) AS last_article_time
    FROM wechat_article_raw GROUP BY account_name
), task_stats AS (
    SELECT raw.account_name,
           SUM(task.task_type = 'clean_article' AND task.status IN ('pending','running')) AS pending_parse_count,
           SUM(task.task_type = 'analyze_article' AND task.status IN ('pending','running')) AS pending_analyze_count,
           SUM(task.status = 'failed') AS failed_count
    FROM wechat_article_process_task task
    JOIN wechat_article_raw raw ON raw.article_hash = task.ref_id
    WHERE task.ref_type = 'article'
    GROUP BY raw.account_name
), log_ranked AS (
    SELECT account_name, status, error_code, error_msg, end_time, start_time,
           ROW_NUMBER() OVER (PARTITION BY account_name ORDER BY start_time DESC, id DESC) AS row_num,
           MAX(CASE WHEN status = 'success' THEN COALESCE(end_time, start_time) END)
             OVER (PARTITION BY account_name) AS last_success_collect_time
    FROM wechat_article_collect_log
), log_latest AS (
    SELECT account_name, status AS last_collect_status,
           COALESCE(error_code, error_msg) AS last_error,
           COALESCE(end_time, start_time) AS latest_collect_log_time,
           last_success_collect_time
    FROM log_ranked WHERE row_num = 1
)
SELECT config.id AS source_id, config.account_name, config.werss_source_id,
       config.enabled AS collection_enabled,
       config.downstream_clean_enabled AS downstream_processing_enabled,
       config.upstream_status,
       config.upstream_last_seen_at,
       raw_stats.last_article_time, log_latest.last_success_collect_time,
       COALESCE(raw_stats.article_count, 0) AS article_count,
       COALESCE(task_stats.pending_parse_count, 0) AS pending_parse_count,
       COALESCE(task_stats.pending_analyze_count, 0) AS pending_analyze_count,
       COALESCE(task_stats.failed_count, 0) AS failed_count,
       log_latest.last_collect_status, log_latest.last_error,
       config.update_time AS updated_at, log_latest.latest_collect_log_time
FROM wechat_public_account_config config
LEFT JOIN raw_stats ON raw_stats.account_name = config.account_name
LEFT JOIN task_stats ON task_stats.account_name = config.account_name
LEFT JOIN log_latest ON log_latest.account_name = config.account_name
WHERE config.werss_source_id IS NOT NULL
  AND config.upstream_status IN ('active', 'disabled')
ORDER BY config.account_name, config.id
LIMIT :limit OFFSET :offset
""")
