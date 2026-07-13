from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ArticleAccountConfigRecord:
    account_name: str
    account_type: str
    feed_url: str | None = None
    source_type: str = "rss"
    request_timeout_seconds: int = 30
    priority: int = 5
    poll_interval_minutes: int = 60
    daily_window_start: str = "07:30"
    daily_window_end: str = "19:30"
    max_articles_per_round: int = 5
    enabled: bool = True
    collect_today_only: bool = True
    dedup_key: str = "article_hash"
    last_success_collect_time: datetime | None = None
    last_feed_etag: str | None = None
    last_feed_modified: str | None = None
    last_error_code: str | None = None
    werss_source_id: str | None = None
    upstream_status: str = "unknown"
    upstream_last_seen_at: datetime | None = None
    upstream_missing_at: datetime | None = None
    remark: str | None = None
    id: int | None = None


class MysqlArticleAccountConfigRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def set_downstream_clean_enabled(self, account_name: str, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("downstream clean enabled must be boolean")
        if not account_name.strip():
            raise ValueError("account_name must not be blank")
        statement = text(
            """
            UPDATE wechat_public_account_config
            SET downstream_clean_enabled = :enabled,
                update_time = CURRENT_TIMESTAMP
            WHERE account_name = :account_name
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {"account_name": account_name, "enabled": 1 if enabled else 0},
            )
            if result.rowcount != 1:
                raise LookupError("article account not found")

    def upsert_account_config(
        self,
        *,
        account_name: str,
        account_type: str,
        feed_url: str,
        source_type: str,
        enabled: bool,
        priority: int,
        poll_interval_minutes: int,
        request_timeout_seconds: int,
        daily_window_start: str,
        daily_window_end: str,
        max_articles_per_round: int,
        collect_today_only: bool,
        dedup_key: str,
        remark: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO wechat_public_account_config (
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                remark
            ) VALUES (
                :account_name,
                :account_type,
                :feed_url,
                :source_type,
                :enabled,
                :priority,
                :poll_interval_minutes,
                :request_timeout_seconds,
                :daily_window_start,
                :daily_window_end,
                :max_articles_per_round,
                :collect_today_only,
                :dedup_key,
                :remark
            )
            ON DUPLICATE KEY UPDATE
                account_type = VALUES(account_type),
                feed_url = VALUES(feed_url),
                source_type = VALUES(source_type),
                enabled = VALUES(enabled),
                priority = VALUES(priority),
                poll_interval_minutes = VALUES(poll_interval_minutes),
                request_timeout_seconds = VALUES(request_timeout_seconds),
                daily_window_start = VALUES(daily_window_start),
                daily_window_end = VALUES(daily_window_end),
                max_articles_per_round = VALUES(max_articles_per_round),
                collect_today_only = VALUES(collect_today_only),
                dedup_key = VALUES(dedup_key),
                remark = VALUES(remark),
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "account_name": account_name,
            "account_type": account_type,
            "feed_url": feed_url,
            "source_type": source_type,
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
            "request_timeout_seconds": request_timeout_seconds,
            "daily_window_start": daily_window_start,
            "daily_window_end": daily_window_end,
            "max_articles_per_round": max_articles_per_round,
            "collect_today_only": 1 if collect_today_only else 0,
            "dedup_key": dedup_key,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def create_account_config(
        self,
        *,
        account_name: str,
        account_type: str,
        feed_url: str,
        source_type: str,
        enabled: bool,
        priority: int,
        poll_interval_minutes: int,
        request_timeout_seconds: int,
        daily_window_start: str,
        daily_window_end: str,
        max_articles_per_round: int,
        collect_today_only: bool,
        dedup_key: str,
        remark: str | None,
    ) -> int:
        statement = text(
            """
            INSERT INTO wechat_public_account_config (
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                remark
            ) VALUES (
                :account_name,
                :account_type,
                :feed_url,
                :source_type,
                :enabled,
                :priority,
                :poll_interval_minutes,
                :request_timeout_seconds,
                :daily_window_start,
                :daily_window_end,
                :max_articles_per_round,
                :collect_today_only,
                :dedup_key,
                :remark
            )
            """
        )
        params = {
            "account_name": account_name,
            "account_type": account_type,
            "feed_url": feed_url,
            "source_type": source_type,
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
            "request_timeout_seconds": request_timeout_seconds,
            "daily_window_start": daily_window_start,
            "daily_window_end": daily_window_end,
            "max_articles_per_round": max_articles_per_round,
            "collect_today_only": 1 if collect_today_only else 0,
            "dedup_key": dedup_key,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.lastrowid)

    def list_accounts(self) -> list[ArticleAccountConfigRecord]:
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                last_feed_etag,
                last_feed_modified,
                last_error_code,
                werss_source_id,
                upstream_status,
                upstream_last_seen_at,
                upstream_missing_at,
                remark
            FROM wechat_public_account_config
            ORDER BY priority ASC, account_name ASC
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def list_accounts_page(
        self, *, limit: int, offset: int
    ) -> list[ArticleAccountConfigRecord]:
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                last_feed_etag,
                last_feed_modified,
                last_error_code,
                werss_source_id,
                upstream_status,
                upstream_last_seen_at,
                upstream_missing_at,
                remark
            FROM wechat_public_account_config
            ORDER BY priority ASC, account_name ASC
            LIMIT :limit
            OFFSET :offset
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(
                statement, {"limit": limit, "offset": offset}
            ).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def list_enabled_articles_for_job(
        self, *, limit: int
    ) -> list[ArticleAccountConfigRecord]:
        _validate_job_choice_limit(limit)
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                last_feed_etag,
                last_feed_modified,
                last_error_code,
                werss_source_id,
                upstream_status,
                upstream_last_seen_at,
                upstream_missing_at,
                remark
            FROM wechat_public_account_config
            WHERE enabled = 1
            ORDER BY priority ASC, account_name ASC, id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(
                statement, {"limit": limit}
            ).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def get_account(self, source_id: int) -> ArticleAccountConfigRecord | None:
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                last_feed_etag,
                last_feed_modified,
                last_error_code,
                werss_source_id,
                upstream_status,
                upstream_last_seen_at,
                upstream_missing_at,
                remark
            FROM wechat_public_account_config
            WHERE id = :source_id
            """
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement, {"source_id": source_id}).mappings().first()
        return None if row is None else self._record_from_row(row)

    def update_account_config(
        self,
        source_id: int,
        *,
        account_name: str,
        account_type: str,
        feed_url: str,
        source_type: str,
        priority: int,
        poll_interval_minutes: int,
        request_timeout_seconds: int,
        daily_window_start: str,
        daily_window_end: str,
        max_articles_per_round: int,
        collect_today_only: bool,
        remark: str | None,
    ) -> int:
        statement = text(
            """
            UPDATE wechat_public_account_config
            SET account_name = :account_name,
                account_type = :account_type,
                feed_url = :feed_url,
                source_type = :source_type,
                priority = :priority,
                poll_interval_minutes = :poll_interval_minutes,
                request_timeout_seconds = :request_timeout_seconds,
                daily_window_start = :daily_window_start,
                daily_window_end = :daily_window_end,
                max_articles_per_round = :max_articles_per_round,
                collect_today_only = :collect_today_only,
                remark = :remark,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :source_id
            """
        )
        params = {
            "source_id": source_id,
            "account_name": account_name,
            "account_type": account_type,
            "feed_url": feed_url,
            "source_type": source_type,
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
            "request_timeout_seconds": request_timeout_seconds,
            "daily_window_start": daily_window_start,
            "daily_window_end": daily_window_end,
            "max_articles_per_round": max_articles_per_round,
            "collect_today_only": 1 if collect_today_only else 0,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.rowcount or 0)

    def set_account_enabled(self, source_id: int, enabled: bool) -> int:
        statement = text(
            """
            UPDATE wechat_public_account_config
            SET enabled = :enabled,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :source_id
            """
        )
        params = {"source_id": source_id, "enabled": 1 if enabled else 0}
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.rowcount or 0)

    def delete_account(self, source_id: int) -> int:
        statement = text(
            """
            DELETE FROM wechat_public_account_config
            WHERE id = :source_id
              AND enabled = 0
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement, {"source_id": source_id})
            return int(result.rowcount or 0)

    def list_due_accounts(self, now: datetime, limit: int) -> list[ArticleAccountConfigRecord]:
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                feed_url,
                source_type,
                enabled,
                priority,
                poll_interval_minutes,
                request_timeout_seconds,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                last_feed_etag,
                last_feed_modified,
                last_error_code,
                werss_source_id,
                upstream_status,
                upstream_last_seen_at,
                upstream_missing_at,
                remark
            FROM wechat_public_account_config
            WHERE enabled = 1
              AND TIME(:now) BETWEEN daily_window_start AND daily_window_end
              AND (
                last_success_collect_time IS NULL
                OR TIMESTAMPDIFF(MINUTE, last_success_collect_time, :now) >= poll_interval_minutes
              )
            ORDER BY priority ASC, last_success_collect_time ASC, account_name ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"now": now, "limit": limit}).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def disable_account(self, account_name: str) -> None:
        statement = text(
            """
            UPDATE wechat_public_account_config
            SET enabled = 0,
                update_time = CURRENT_TIMESTAMP
            WHERE account_name = :account_name
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"account_name": account_name})

    def update_feed_state(self, source_id: int, *, etag: str | None,
                          modified: str | None, success_time: datetime | None,
                          error_code: str | None) -> None:
        statement = text("""
            UPDATE wechat_public_account_config
            SET last_feed_etag = :etag,
                last_feed_modified = :modified,
                last_success_collect_time = COALESCE(:success_time, last_success_collect_time),
                last_error_code = :error_code,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :source_id
        """)
        params = {"source_id": source_id, "etag": etag, "modified": modified,
                  "success_time": success_time, "error_code": error_code}
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def _record_from_row(self, row) -> ArticleAccountConfigRecord:
        return ArticleAccountConfigRecord(
            account_name=str(row["account_name"]),
            account_type=str(row["account_type"]),
            feed_url=row.get("feed_url"),
            source_type=str(row.get("source_type", "rss")),
            request_timeout_seconds=int(row.get("request_timeout_seconds", 30)),
            priority=int(row["priority"]),
            poll_interval_minutes=int(row["poll_interval_minutes"]),
            daily_window_start=_format_time_value(row["daily_window_start"]),
            daily_window_end=_format_time_value(row["daily_window_end"]),
            max_articles_per_round=int(row["max_articles_per_round"]),
            enabled=bool(row["enabled"]),
            collect_today_only=bool(row["collect_today_only"]),
            dedup_key=str(row["dedup_key"]),
            last_success_collect_time=row["last_success_collect_time"],
            last_feed_etag=row.get("last_feed_etag"),
            last_feed_modified=row.get("last_feed_modified"),
            last_error_code=row.get("last_error_code"),
            werss_source_id=row.get("werss_source_id"),
            upstream_status=str(row.get("upstream_status", "unknown")),
            upstream_last_seen_at=row.get("upstream_last_seen_at"),
            upstream_missing_at=row.get("upstream_missing_at"),
            remark=row["remark"],
            id=None if row.get("id") is None else int(row["id"]),
        )


def _format_time_value(value) -> str:
    text = str(value)
    parts = text.split(":")
    if len(parts) == 3 and len(parts[0]) == 1:
        return f"0{text}"
    return text


def _validate_job_choice_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
