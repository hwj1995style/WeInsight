from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.storage.source_mutation_repo import MysqlSourceWriteGuard


_SOURCE_WRITE_GUARD = MysqlSourceWriteGuard()


@dataclass(frozen=True)
class ArticleCollectLogRecord:
    batch_id: str
    account_name: str
    start_time: datetime
    end_time: datetime | None
    status: str
    stage: str | None = None
    link_count: int = 0
    insert_count: int = 0
    error_code: str | None = None
    error_msg: str | None = None
    screenshot_path: str | None = None


class MysqlArticleCollectLogRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_collect_log(self, record: ArticleCollectLogRecord) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_collect_log (
                batch_id,
                account_name,
                start_time,
                end_time,
                link_count,
                insert_count,
                status,
                stage,
                error_code,
                error_msg,
                screenshot_path
            ) VALUES (
                :batch_id,
                :account_name,
                :start_time,
                :end_time,
                :link_count,
                :insert_count,
                :status,
                :stage,
                :error_code,
                :error_msg,
                :screenshot_path
            )
            """
        )
        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "article", record.account_name
            )
            connection.execute(statement, record.__dict__)
