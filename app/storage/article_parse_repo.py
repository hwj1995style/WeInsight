from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.article_parsing import ArticleParseSource, CleanArticleRecord


class MysqlArticleParseRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_pending_parse_articles(self, limit: int) -> list[ArticleParseSource]:
        statement = text(
            """
            SELECT
                raw.article_hash,
                raw.account_name,
                raw.title,
                raw.article_url,
                raw.publish_time,
                raw.author,
                raw.digest,
                raw.content_locator,
                raw.content_locator_type
            FROM wechat_article_process_task task
            JOIN wechat_article_raw raw
              ON raw.article_hash = task.ref_id
            WHERE task.task_type = 'clean_article'
              AND task.ref_type = 'article'
              AND task.status = 'pending'
              AND (task.next_run_time IS NULL OR task.next_run_time <= CURRENT_TIMESTAMP)
            ORDER BY task.create_time ASC, task.id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings().all()

        return [
            ArticleParseSource(
                article_hash=str(row["article_hash"]),
                account_name=str(row["account_name"]),
                title=str(row["title"] or ""),
                article_url=str(row["article_url"]),
                publish_time=row["publish_time"],
                author=row["author"],
                digest=row["digest"],
                content_locator=row["content_locator"],
                content_locator_type=row["content_locator_type"],
            )
            for row in rows
        ]

    def upsert_clean_article(self, article: CleanArticleRecord) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_clean (
                article_hash,
                account_name,
                title,
                article_url,
                publish_time,
                author,
                digest,
                content_length,
                parse_time,
                parse_version,
                content_source,
                content_hash,
                content_fetch_status
            ) VALUES (
                :article_hash,
                :account_name,
                :title,
                :article_url,
                :publish_time,
                :author,
                :digest,
                :content_length,
                :parse_time,
                :parse_version,
                :content_source,
                :content_hash,
                :content_fetch_status
            )
            ON DUPLICATE KEY UPDATE
                account_name = VALUES(account_name),
                title = VALUES(title),
                article_url = VALUES(article_url),
                publish_time = VALUES(publish_time),
                author = VALUES(author),
                digest = VALUES(digest),
                content_length = VALUES(content_length),
                parse_time = VALUES(parse_time),
                parse_version = VALUES(parse_version),
                content_source = VALUES(content_source),
                content_hash = VALUES(content_hash),
                content_fetch_status = VALUES(content_fetch_status)
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, article.__dict__)

    def create_analyze_task(self, article_hash: str) -> None:
        statement = text(
            """
            INSERT IGNORE INTO wechat_article_process_task (
                task_type,
                ref_type,
                ref_id,
                status
            ) VALUES (
                :task_type,
                'article',
                :ref_id,
                'pending'
            )
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"task_type": "analyze_article", "ref_id": article_hash})

    def mark_clean_task_success(self, article_hash: str) -> None:
        statement = text(
            """
            UPDATE wechat_article_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'clean_article'
              AND ref_type = 'article'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": article_hash})

    def mark_clean_task_failed(self, article_hash: str, error_msg: str) -> None:
        statement = text(
            """
            UPDATE wechat_article_process_task
            SET status = CASE WHEN retry_count + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                retry_count = retry_count + 1,
                next_run_time = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 60 SECOND),
                error_msg = :error_msg,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'clean_article'
              AND ref_type = 'article'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": article_hash, "error_msg": error_msg})
