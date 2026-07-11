from datetime import datetime
from types import SimpleNamespace
import threading
import time
from app.rss.feed_client import FeedFetchError

from app.pipelines.rss_article_collect_service import RssArticleCollectResult

NOW = datetime(2026, 7, 11, 12)

class Service:
    def collect_once(self, target, **kwargs):
        if target.account_name == "bad": raise RuntimeError("boom")
        return RssArticleCollectResult(1, 1, 0, 0, 1, None, None, False, 4, 200)
class Logs:
    def __init__(self): self.rows=[]
    def insert_collect_log(self, row): self.rows.append(row)

class StateRepo:
    def __init__(self): self.calls=[]
    def update_feed_state(self, source_id, **kwargs): self.calls.append((source_id, kwargs))

class StatefulService(Service):
    def __init__(self, errors): self.state_repo=StateRepo(); self.errors=iter(errors)
    def collect_once(self, target, **kwargs):
        error = next(self.errors, None)
        if error: raise error
        self.state_repo.update_feed_state(target.id, etag=target.last_feed_etag,
            modified=target.last_feed_modified, success_time=NOW, error_code=None)
        return super().collect_once(target, **kwargs)

class FailingLogs(Logs):
    def __init__(self, failures): super().__init__(); self.failures = iter(failures)
    def insert_collect_log(self, row):
        if next(self.failures, False): raise RuntimeError("log down")
        super().insert_collect_log(row)

def test_one_failed_feed_does_not_block_next_target():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    logs=Logs(); runner=RssArticlePollingRunner(collect_service=Service(), log_repo=logs, batch_id_factory=lambda n: n)
    result=runner.run([SimpleNamespace(account_name="bad"), SimpleNamespace(account_name="good")], now=NOW)
    assert result.failed_count == 1 and result.success_count == 1
    assert logs.rows[0].error_code == "RSS_ARTICLE_COLLECT_ERROR"
    assert all(row.screenshot_path is None for row in logs.rows)

def test_stop_is_checked_only_after_completed_target():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    calls=[]
    runner=RssArticlePollingRunner(collect_service=Service(), log_repo=Logs(), batch_id_factory=lambda n:n)
    result=runner.run([SimpleNamespace(account_name="good"), SimpleNamespace(account_name="next")], now=NOW, stop_requested_provider=lambda: calls.append(1) or True)
    assert result.attempted_count == 1 and result.stop_requested_count == 1

def test_success_log_failure_counts_only_failure_and_does_not_block_next_target():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    runner=RssArticlePollingRunner(collect_service=Service(), log_repo=FailingLogs([True, False, False]), batch_id_factory=lambda n:n)
    result=runner.run([SimpleNamespace(account_name="good"), SimpleNamespace(account_name="next")], now=NOW)
    assert result.attempted_count == 2 and result.success_count == 1 and result.failed_count == 1

def test_failure_log_failure_is_isolated_from_next_target():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    runner=RssArticlePollingRunner(collect_service=Service(), log_repo=FailingLogs([True, False]), batch_id_factory=lambda n:n)
    result=runner.run([SimpleNamespace(account_name="bad"), SimpleNamespace(account_name="good")], now=NOW)
    assert result.attempted_count == 2 and result.success_count == 1 and result.failed_count == 1


def test_multiple_feeds_run_concurrently_with_configured_cap():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    class BlockingService(Service):
        def __init__(self):
            self.lock = threading.Lock(); self.active = 0; self.peak = 0
        def collect_once(self, target, **kwargs):
            with self.lock:
                self.active += 1; self.peak = max(self.peak, self.active)
            time.sleep(0.04)
            with self.lock: self.active -= 1
            return super().collect_once(target, **kwargs)

    service = BlockingService()
    runner = RssArticlePollingRunner(
        collect_service=service, log_repo=Logs(), batch_id_factory=lambda n: n,
        max_concurrency=2,
    )
    result = runner.run(
        [SimpleNamespace(account_name=f"feed-{index}") for index in range(5)], NOW
    )
    assert result.success_count == 5
    assert 1 < service.peak <= 2


def test_structured_and_generic_failures_persist_error_without_cache_or_success_fields():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    target = SimpleNamespace(id=7, account_name="feed", last_feed_etag="etag", last_feed_modified="mod")
    for error, code in ((FeedFetchError("feed_timeout"), "feed_timeout"), (RuntimeError("boom"), "RSS_ARTICLE_COLLECT_ERROR")):
        service = StatefulService([error])
        RssArticlePollingRunner(collect_service=service, log_repo=Logs(), batch_id_factory=lambda n:n).run([target], NOW)
        assert service.state_repo.calls == [(7, {"error_code": code})]


def test_success_after_failure_clears_error_and_preserves_cache_values():
    from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
    target = SimpleNamespace(id=8, account_name="feed", last_feed_etag="etag", last_feed_modified="mod")
    service = StatefulService([FeedFetchError("feed_timeout"), None])
    runner = RssArticlePollingRunner(collect_service=service, log_repo=Logs(), batch_id_factory=lambda n:n)
    runner.run([target], NOW); runner.run([target], NOW)
    assert service.state_repo.calls[0] == (8, {"error_code": "feed_timeout"})
    assert service.state_repo.calls[1][1] == {"etag": "etag", "modified": "mod", "success_time": NOW, "error_code": None}
