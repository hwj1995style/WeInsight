from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


ARTICLE_TASK_TYPES = {"clean_article", "analyze_article"}


@dataclass(frozen=True)
class ArticleFailedTaskRecord:
    id: int
    task_type: str
    ref_type: str
    ref_id: str
    status: str
    retry_count: int
    next_run_time: datetime | None
    error_summary: str | None
    update_time: datetime | None


class MysqlArticleTaskAdminRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_failed_tasks(self, task_type: str | None = None, limit: int = 50) -> list[ArticleFailedTaskRecord]:
        _validate_positive_limit(limit)
        _validate_article_task_type(task_type)
        filters = ["status = 'failed'"]
        params: dict[str, object] = {"limit": limit}
        if task_type:
            filters.append("task_type = :task_type")
            params["task_type"] = task_type

        statement = text(
            f"""
            SELECT
                id,
                task_type,
                ref_type,
                ref_id,
                status,
                retry_count,
                next_run_time,
                LEFT(COALESCE(error_msg, ''), 200) AS error_summary,
                update_time
            FROM wechat_article_process_task
            WHERE {" AND ".join(filters)}
            ORDER BY update_time DESC, id DESC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [_row_to_failed_task(row) for row in rows]

    def retry_failed_tasks(self, task_type: str | None = None, limit: int = 50) -> int:
        _validate_positive_limit(limit)
        _validate_article_task_type(task_type)
        filters = ["status = 'failed'"]
        params: dict[str, object] = {"limit": limit}
        if task_type:
            filters.append("task_type = :task_type")
            params["task_type"] = task_type

        statement = text(
            f"""
            UPDATE wechat_article_process_task
            SET status = 'pending',
                retry_count = 0,
                next_run_time = CURRENT_TIMESTAMP,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE {" AND ".join(filters)}
            ORDER BY update_time DESC, id DESC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
        return int(result.rowcount or 0)


def _row_to_failed_task(row) -> ArticleFailedTaskRecord:
    return ArticleFailedTaskRecord(
        id=int(row["id"]),
        task_type=str(row["task_type"]),
        ref_type=str(row["ref_type"]),
        ref_id=str(row["ref_id"]),
        status=str(row["status"]),
        retry_count=int(row["retry_count"] or 0),
        next_run_time=row["next_run_time"],
        error_summary=_safe_error_summary(row["error_summary"]),
        update_time=row["update_time"],
    )


def _safe_error_summary(value) -> str | None:
    summary = str(value or "").strip()
    if not summary:
        return None
    summary = re.sub(r"https?://\S+", "[redacted-url]", summary)
    summary = re.sub(r"mp\.weixin\.qq\.com/\S+", "[redacted-url]", summary)
    summary = re.sub(r"\s+", " ", summary)
    return summary[:200]


def _validate_article_task_type(task_type: str | None) -> None:
    if task_type is not None and task_type not in ARTICLE_TASK_TYPES:
        raise ValueError(f"unsupported article task_type: {task_type}")


def _validate_positive_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
