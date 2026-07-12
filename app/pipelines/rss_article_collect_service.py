from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from collections.abc import Callable

from app.rss.article_mapper import FeedItemInvalid, map_feed_item
from app.storage.article_config_repo import ArticleAccountConfigRecord


RssArticleTarget = ArticleAccountConfigRecord


@dataclass(frozen=True)
class RssArticleCollectResult:
    feed_item_count: int
    insert_count: int
    duplicate_count: int
    invalid_count: int
    task_created_count: int
    etag: str | None
    modified: str | None
    not_modified: bool
    elapsed_ms: int
    http_status: int | None = None


class RssArticleCollectService:
    def __init__(self, *, feed_client, raw_repo, state_repo) -> None:
        self.feed_client = feed_client
        self.raw_repo = raw_repo
        self.state_repo = state_repo

    def collect_once(self, target: RssArticleTarget, *, batch_id: str,
                     collect_time: datetime,
                     after_fetch_checkpoint: Callable[[], None] | None = None) -> RssArticleCollectResult:
        fetched = self.feed_client.fetch(
            target.feed_url, timeout_seconds=target.request_timeout_seconds,
            etag=target.last_feed_etag, modified=target.last_feed_modified)
        if after_fetch_checkpoint is not None:
            after_fetch_checkpoint()
        etag = fetched.etag if fetched.etag is not None else target.last_feed_etag
        modified = fetched.modified if fetched.modified is not None else target.last_feed_modified
        records = []
        invalid_count = 0
        for item in fetched.items:
            try:
                records.append(map_feed_item(item=item, account_name=target.account_name,
                                             batch_id=batch_id, collect_time=collect_time))
            except FeedItemInvalid:
                invalid_count += 1
        if target.last_success_collect_time is None:
            cutoff = collect_time.replace(tzinfo=None) - timedelta(hours=24)
            records = sorted((r for r in records if r.publish_time and r.publish_time >= cutoff),
                             key=lambda r: r.publish_time, reverse=True)[:30]
        inserted = self.raw_repo.insert_raw_ignore_duplicates(records)
        self.state_repo.update_feed_state(target.id, etag=etag, modified=modified,
                                          success_time=collect_time, error_code=None)
        return RssArticleCollectResult(len(fetched.items), inserted.inserted_count,
            inserted.duplicate_count, invalid_count, inserted.task_created_count,
            etag, modified, fetched.not_modified, fetched.elapsed_ms, fetched.status_code)
