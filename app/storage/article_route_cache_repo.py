from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ArticleRouteCacheRecord:
    account_name: str
    route_type: str
    link_extract_type: str
    entry_label: str | None = None
    entry_index: int | None = None
    cache_status: str = "active"
    failure_count: int = 0
    last_error_code: str | None = None
    last_error_msg: str | None = None


class MysqlArticleRouteCacheRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_active_route(self, account_name: str) -> ArticleRouteCacheRecord | None:
        statement = text(
            """
            SELECT
                account_name,
                route_type,
                entry_label,
                entry_index,
                link_extract_type,
                cache_status,
                failure_count,
                last_error_code,
                last_error_msg
            FROM wechat_article_route_cache
            WHERE account_name = :account_name
              AND cache_status = 'active'
            """
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement, {"account_name": account_name}).mappings().first()
        if row is None:
            return None
        return ArticleRouteCacheRecord(
            account_name=str(row["account_name"]),
            route_type=str(row["route_type"]),
            entry_label=row["entry_label"],
            entry_index=None if row["entry_index"] is None else int(row["entry_index"]),
            link_extract_type=str(row["link_extract_type"]),
            cache_status=str(row["cache_status"]),
            failure_count=int(row["failure_count"] or 0),
            last_error_code=row["last_error_code"],
            last_error_msg=row["last_error_msg"],
        )

    def upsert_success(
        self,
        *,
        account_name: str,
        route_type: str,
        link_extract_type: str,
        entry_label: str | None,
        entry_index: int | None,
        success_time: datetime,
    ) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_route_cache (
                account_name,
                route_type,
                entry_label,
                entry_index,
                link_extract_type,
                cache_status,
                last_success_at,
                failure_count,
                last_error_code,
                last_error_msg
            ) VALUES (
                :account_name,
                :route_type,
                :entry_label,
                :entry_index,
                :link_extract_type,
                'active',
                :success_time,
                0,
                NULL,
                NULL
            )
            ON DUPLICATE KEY UPDATE
                route_type = VALUES(route_type),
                entry_label = VALUES(entry_label),
                entry_index = VALUES(entry_index),
                link_extract_type = VALUES(link_extract_type),
                cache_status = 'active',
                last_success_at = VALUES(last_success_at),
                failure_count = 0,
                last_error_code = NULL,
                last_error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "account_name": account_name,
                    "route_type": route_type,
                    "entry_label": entry_label,
                    "entry_index": entry_index,
                    "link_extract_type": link_extract_type,
                    "success_time": success_time,
                },
            )

    def mark_failure(
        self,
        *,
        account_name: str,
        error_code: str,
        error_msg: str,
        failure_time: datetime,
        failure_threshold: int,
    ) -> None:
        statement = text(
            """
            UPDATE wechat_article_route_cache
            SET failure_count = failure_count + 1,
                cache_status = CASE
                    WHEN failure_count + 1 >= :failure_threshold THEN 'invalid'
                    ELSE cache_status
                END,
                last_failure_at = :failure_time,
                last_error_code = :error_code,
                last_error_msg = :error_msg,
                update_time = CURRENT_TIMESTAMP
            WHERE account_name = :account_name
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "account_name": account_name,
                    "error_code": error_code,
                    "error_msg": _safe_error_msg(error_msg),
                    "failure_time": failure_time,
                    "failure_threshold": failure_threshold,
                },
            )


def _safe_error_msg(value: str) -> str:
    text_value = re.sub(r"https?://\S+", "[redacted-url]", value)
    text_value = re.sub(r"mp\.weixin\.qq\.com/\S+", "[redacted-url]", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value[:500]
