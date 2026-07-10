from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class RawArticleRecord:
    article_hash: str
    account_name: str
    title: str
    article_url: str
    publish_time: datetime | None
    collect_time: datetime
    author: str | None = None
    digest: str | None = None
    collect_batch_id: str | None = None


@dataclass(frozen=True)
class ArticleRawInsertResult:
    read_count: int
    inserted_count: int
    duplicate_count: int
    skipped_count: int
    task_created_count: int


class MysqlArticleRawRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_today_raw_ignore_duplicates(
        self,
        articles: Iterable[RawArticleRecord],
        *,
        crawl_date: date,
    ) -> ArticleRawInsertResult:
        read_count = 0
        inserted_count = 0
        duplicate_count = 0
        skipped_count = 0
        task_created_count = 0

        with self.engine.begin() as connection:
            for article in articles:
                read_count += 1
                if article.publish_time is None or article.publish_time.date() != crawl_date:
                    skipped_count += 1
                    continue

                duplicate_url = connection.execute(
                    _SELECT_DUPLICATE_ARTICLE_URL_SQL,
                    {
                        "account_name": article.account_name,
                        "publish_date": crawl_date,
                        "article_url": article.article_url,
                    },
                ).first()
                if duplicate_url is not None:
                    duplicate_count += 1
                    continue

                raw_result = connection.execute(
                    _INSERT_ARTICLE_RAW_SQL,
                    {
                        "article_hash": article.article_hash,
                        "account_name": article.account_name,
                        "title": article.title,
                        "article_url": article.article_url,
                        "publish_time": article.publish_time,
                        "publish_date": crawl_date,
                        "author": article.author,
                        "digest": article.digest,
                        "collect_batch_id": article.collect_batch_id,
                        "collect_time": article.collect_time,
                    },
                )

                if raw_result.rowcount <= 0:
                    duplicate_count += 1
                    continue

                inserted_count += 1
                task_result = connection.execute(
                    _INSERT_CLEAN_ARTICLE_TASK_SQL,
                    {
                        "task_type": "clean_article",
                        "ref_type": "article",
                        "ref_id": article.article_hash,
                    },
                )
                if task_result.rowcount > 0:
                    task_created_count += task_result.rowcount

        return ArticleRawInsertResult(
            read_count=read_count,
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            skipped_count=skipped_count,
            task_created_count=task_created_count,
        )


_SELECT_DUPLICATE_ARTICLE_URL_SQL = text(
    """
    SELECT 1
    FROM wechat_article_raw
    WHERE account_name = :account_name
      AND publish_date = :publish_date
      AND article_url = :article_url
    LIMIT 1
    """
)


_INSERT_ARTICLE_RAW_SQL = text(
    """
    INSERT IGNORE INTO wechat_article_raw (
        article_hash,
        account_name,
        title,
        article_url,
        publish_time,
        publish_date,
        author,
        digest,
        collect_batch_id,
        collect_time
    ) VALUES (
        :article_hash,
        :account_name,
        :title,
        :article_url,
        :publish_time,
        :publish_date,
        :author,
        :digest,
        :collect_batch_id,
        :collect_time
    )
    """
)

_INSERT_CLEAN_ARTICLE_TASK_SQL = text(
    """
    INSERT IGNORE INTO wechat_article_process_task (
        task_type,
        ref_type,
        ref_id,
        status
    ) VALUES (
        :task_type,
        :ref_type,
        :ref_id,
        'pending'
    )
    """
)
