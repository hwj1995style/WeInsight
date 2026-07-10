from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ArticleAccountConfigRecord:
    account_name: str
    account_type: str
    priority: int
    poll_interval_minutes: int
    daily_window_start: str
    daily_window_end: str
    max_articles_per_round: int
    enabled: bool = True
    collect_today_only: bool = True
    dedup_key: str = "article_hash"
    last_success_collect_time: datetime | None = None
    remark: str | None = None
    id: int | None = None


class MysqlArticleAccountConfigRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_account_config(
        self,
        *,
        account_name: str,
        account_type: str,
        enabled: bool,
        priority: int,
        poll_interval_minutes: int,
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
                enabled,
                priority,
                poll_interval_minutes,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                remark
            ) VALUES (
                :account_name,
                :account_type,
                :enabled,
                :priority,
                :poll_interval_minutes,
                :daily_window_start,
                :daily_window_end,
                :max_articles_per_round,
                :collect_today_only,
                :dedup_key,
                :remark
            )
            ON DUPLICATE KEY UPDATE
                account_type = VALUES(account_type),
                enabled = VALUES(enabled),
                priority = VALUES(priority),
                poll_interval_minutes = VALUES(poll_interval_minutes),
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
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
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
        enabled: bool,
        priority: int,
        poll_interval_minutes: int,
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
                enabled,
                priority,
                poll_interval_minutes,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                remark
            ) VALUES (
                :account_name,
                :account_type,
                :enabled,
                :priority,
                :poll_interval_minutes,
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
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
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
                enabled,
                priority,
                poll_interval_minutes,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
                remark
            FROM wechat_public_account_config
            ORDER BY priority ASC, account_name ASC
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def get_account(self, source_id: int) -> ArticleAccountConfigRecord | None:
        statement = text(
            """
            SELECT
                id,
                account_name,
                account_type,
                enabled,
                priority,
                poll_interval_minutes,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
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
        priority: int,
        poll_interval_minutes: int,
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
                priority = :priority,
                poll_interval_minutes = :poll_interval_minutes,
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
            "priority": priority,
            "poll_interval_minutes": poll_interval_minutes,
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
                enabled,
                priority,
                poll_interval_minutes,
                daily_window_start,
                daily_window_end,
                max_articles_per_round,
                collect_today_only,
                dedup_key,
                last_success_collect_time,
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

    def _record_from_row(self, row) -> ArticleAccountConfigRecord:
        return ArticleAccountConfigRecord(
            account_name=str(row["account_name"]),
            account_type=str(row["account_type"]),
            priority=int(row["priority"]),
            poll_interval_minutes=int(row["poll_interval_minutes"]),
            daily_window_start=_format_time_value(row["daily_window_start"]),
            daily_window_end=_format_time_value(row["daily_window_end"]),
            max_articles_per_round=int(row["max_articles_per_round"]),
            enabled=bool(row["enabled"]),
            collect_today_only=bool(row["collect_today_only"]),
            dedup_key=str(row["dedup_key"]),
            last_success_collect_time=row["last_success_collect_time"],
            remark=row["remark"],
            id=None if row.get("id") is None else int(row["id"]),
        )


def _format_time_value(value) -> str:
    text = str(value)
    parts = text.split(":")
    if len(parts) == 3 and len(parts[0]) == 1:
        return f"0{text}"
    return text
