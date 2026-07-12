from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.rss.models import FeedFetchResult, FeedItem
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.storage.article_raw_repo import ArticleRawInsertResult

NOW = datetime(2026, 7, 11, 12)


class Feed:
    def __init__(self, items, *, status=200, etag=None, modified=None, not_modified=False):
        self.result = FeedFetchResult(status, etag, modified, tuple(items), not_modified, 7)
    def fetch(self, *args, **kwargs):
        return self.result


class Raw:
    def __init__(self): self.saved = []
    def insert_raw_ignore_duplicates(self, rows):
        self.saved = rows
        return ArticleRawInsertResult(len(rows), len(rows), 0, 0, len(rows))


class State:
    def __init__(self): self.calls = []
    def update_feed_state(self, source_id, **kwargs): self.calls.append((source_id, kwargs))


def item(i, age_hours=1):
    return FeedItem(f"t{i}", f"https://mp.weixin.qq.com/s/{i}",
                    (NOW - timedelta(hours=age_hours)).isoformat(), None, None, None)


def target(**changes):
    values = dict(id=1, account_name="a", account_type="industry", feed_url="https://feed.example/rss",
                  request_timeout_seconds=30, last_success_collect_time=None,
                  last_feed_etag='"old"', last_feed_modified="old-date")
    values.update(changes)
    return ArticleAccountConfigRecord(**values)


def test_first_collection_keeps_last_24_hours_and_at_most_30():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    raw = Raw()
    result = RssArticleCollectService(feed_client=Feed([item(i) for i in range(40)]), raw_repo=raw, state_repo=State()).collect_once(target(), batch_id="b1", collect_time=NOW)
    assert result.feed_item_count == 40
    assert result.insert_count == 30


def test_first_collection_accepts_timezone_aware_worker_collect_time():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService

    worker_now = NOW.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    result = RssArticleCollectService(
        feed_client=Feed([item(1)]), raw_repo=Raw(), state_repo=State()
    ).collect_once(target(), batch_id="b-aware", collect_time=worker_now)

    assert result.insert_count == 1


def test_invalid_item_does_not_abort_valid_items():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    bad = FeedItem("", "bad", None, None, None, None)
    result = RssArticleCollectService(feed_client=Feed([bad, item(1)]), raw_repo=Raw(), state_repo=State()).collect_once(target(last_success_collect_time=NOW-timedelta(days=1)), batch_id="b2", collect_time=NOW)
    assert result.insert_count == 1
    assert result.invalid_count == 1


def test_304_is_success_and_preserves_missing_cache_values():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    state = State()
    result = RssArticleCollectService(feed_client=Feed([], status=304, etag=None, modified=None, not_modified=True), raw_repo=Raw(), state_repo=state).collect_once(target(), batch_id="b", collect_time=NOW)
    assert result.not_modified and result.insert_count == 0
    assert state.calls[-1][1]["etag"] == '"old"'
    assert state.calls[-1][1]["modified"] == "old-date"


def test_stop_checkpoint_after_fetch_prevents_raw_writes():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    raw = Raw()
    try:
        RssArticleCollectService(feed_client=Feed([item(1)]), raw_repo=raw, state_repo=State()).collect_once(
            target(), batch_id="b", collect_time=NOW,
            after_fetch_checkpoint=lambda: (_ for _ in ()).throw(RuntimeError("stop")))
    except RuntimeError as exc:
        assert str(exc) == "stop"
    assert raw.saved == []


def test_non_first_collection_is_not_capped_and_partial_cache_header_is_preserved():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    raw, state = Raw(), State()
    result = RssArticleCollectService(
        feed_client=Feed([item(i, age_hours=48) for i in range(40)], etag='"new"'),
        raw_repo=raw, state_repo=state).collect_once(
            target(last_success_collect_time=NOW-timedelta(days=1)), batch_id="b", collect_time=NOW)
    assert result.insert_count == 40
    assert result.etag == '"new"' and result.modified == "old-date"


def test_empty_200_is_success():
    from app.pipelines.rss_article_collect_service import RssArticleCollectService
    result = RssArticleCollectService(feed_client=Feed([]), raw_repo=Raw(), state_repo=State()).collect_once(
        target(), batch_id="b", collect_time=NOW)
    assert result.feed_item_count == result.insert_count == 0
    assert not result.not_modified
