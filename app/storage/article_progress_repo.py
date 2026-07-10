from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.pipelines.article_interrupt_resume import ArticleCollectProgressRecord
from app.storage.source_mutation_repo import MysqlSourceWriteGuard


_SOURCE_WRITE_GUARD = MysqlSourceWriteGuard()


class MysqlArticleProgressRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_progress(self, crawl_date: date, account_name: str) -> ArticleCollectProgressRecord | None:
        statement = text(
            """
            SELECT
                crawl_date,
                account_name,
                stage,
                last_article_url,
                status,
                retry_count,
                last_error_code,
                last_error_msg
            FROM wechat_article_collect_progress
            WHERE crawl_date = :crawl_date
              AND account_name = :account_name
            LIMIT 1
            """
        )
        with self.engine.begin() as connection:
            row = connection.execute(
                statement,
                {"crawl_date": crawl_date, "account_name": account_name},
            ).mappings().first()
        if row is None:
            return None
        return ArticleCollectProgressRecord(
            crawl_date=row["crawl_date"],
            account_name=str(row["account_name"]),
            stage=str(row["stage"]),
            status=str(row["status"]),
            last_article_url=row["last_article_url"],
            retry_count=int(row["retry_count"] or 0),
            last_error_code=row["last_error_code"],
            last_error_msg=row["last_error_msg"],
        )

    def upsert_progress(self, record: ArticleCollectProgressRecord) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_collect_progress (
                crawl_date,
                account_name,
                stage,
                last_article_url,
                status,
                retry_count,
                last_error_code,
                last_error_msg
            ) VALUES (
                :crawl_date,
                :account_name,
                :stage,
                :last_article_url,
                :status,
                :retry_count,
                :last_error_code,
                :last_error_msg
            )
            ON DUPLICATE KEY UPDATE
                stage = VALUES(stage),
                last_article_url = VALUES(last_article_url),
                status = VALUES(status),
                retry_count = retry_count + 1,
                last_error_code = VALUES(last_error_code),
                last_error_msg = VALUES(last_error_msg),
                update_time = CURRENT_TIMESTAMP
            """
        )
        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "article", record.account_name
            )
            connection.execute(statement, record.__dict__)

    def mark_success(
        self,
        crawl_date: date,
        account_name: str,
        success_time: datetime | None = None,
    ) -> None:
        progress_statement = text(
            """
            INSERT INTO wechat_article_collect_progress (
                crawl_date,
                account_name,
                stage,
                status,
                retry_count
            ) VALUES (
                :crawl_date,
                :account_name,
                'done',
                'success',
                0
            )
            ON DUPLICATE KEY UPDATE
                stage = 'done',
                status = 'success',
                last_error_code = NULL,
                last_error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            """
        )
        account_statement = text(
            """
            UPDATE wechat_public_account_config
            SET last_success_collect_time = :success_time,
                update_time = CURRENT_TIMESTAMP
            WHERE account_name = :account_name
            """
        )
        success_time = success_time or datetime.now()
        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "article", account_name
            )
            connection.execute(progress_statement, {"crawl_date": crawl_date, "account_name": account_name})
            connection.execute(
                account_statement,
                {"account_name": account_name, "success_time": success_time},
            )
