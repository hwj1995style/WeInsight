from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from collections.abc import Callable
from typing import Protocol

from app.domain.hashes import article_hash
from app.pipelines.article_pipeline import ArticleStage
from app.rpa.interfaces import WechatArticleRpaClient
from app.storage.article_raw_repo import ArticleRawInsertResult, RawArticleRecord


@dataclass(frozen=True)
class ArticleCollectResult:
    account_name: str
    batch_id: str
    link_count: int
    insert_count: int
    duplicate_count: int
    skipped_count: int
    task_created_count: int


class ArticleRawRepo(Protocol):
    def insert_today_raw_ignore_duplicates(
        self,
        articles: list[RawArticleRecord],
        *,
        crawl_date: date,
    ) -> ArticleRawInsertResult:
        ...


class ArticleCollectService:
    def __init__(self, *, rpa: WechatArticleRpaClient, raw_repo: ArticleRawRepo) -> None:
        self.rpa = rpa
        self.raw_repo = raw_repo

    def collect_once(
        self,
        *,
        account_name: str,
        batch_id: str,
        collect_time: datetime,
        max_articles: int,
        resume_after_url: str | None = None,
        checkpoint: Callable[[ArticleStage, str | None], None] | None = None,
    ) -> ArticleCollectResult:
        self.rpa.open_public_account(account_name)
        if checkpoint is not None:
            checkpoint(ArticleStage.OPEN_ACCOUNT, None)

        links = self.rpa.copy_latest_article_links(max_articles)
        links = _links_after_resume_url(links, resume_after_url)
        if checkpoint is not None:
            checkpoint(ArticleStage.COPY_LINKS, None)

        raw_articles = [
            self._raw_article_from_discovered_link(
                account_name=account_name,
                article_url=article_url,
                index=index,
                batch_id=batch_id,
                collect_time=collect_time,
            )
            for index, article_url in enumerate(links, start=1)
        ]

        insert_result = self.raw_repo.insert_today_raw_ignore_duplicates(
            raw_articles,
            crawl_date=collect_time.date(),
        )
        last_article_url = links[-1] if links else resume_after_url
        if checkpoint is not None:
            checkpoint(ArticleStage.SAVE_LINKS, last_article_url)

        return ArticleCollectResult(
            account_name=account_name,
            batch_id=batch_id,
            link_count=len(links),
            insert_count=insert_result.inserted_count,
            duplicate_count=insert_result.duplicate_count,
            skipped_count=insert_result.skipped_count,
            task_created_count=insert_result.task_created_count,
        )

    def _raw_article_from_discovered_link(
        self,
        *,
        account_name: str,
        article_url: str,
        index: int,
        batch_id: str,
        collect_time: datetime,
    ) -> RawArticleRecord:
        # The real title and publish_time are refreshed by Playwright parse in the clean layer.
        title = f"{account_name} article {index}"
        return RawArticleRecord(
            article_hash=article_hash(
                account_name=account_name,
                title=title,
                publish_time=collect_time,
                url=article_url,
            ),
            account_name=account_name,
            title=title,
            article_url=article_url,
            publish_time=collect_time,
            collect_time=collect_time,
            collect_batch_id=batch_id,
        )


def _links_after_resume_url(links: list[str], resume_after_url: str | None) -> list[str]:
    if resume_after_url is None:
        return links
    if resume_after_url not in links:
        return links
    return links[links.index(resume_after_url) + 1 :]
