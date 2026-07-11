from datetime import datetime
from types import SimpleNamespace
import threading
import time

from app.pipelines.rss_article_collect_service import RssArticleCollectResult

NOW = datetime(2026, 7, 11, 12)

class Service:
    def collect_once(self, target, **kwargs):
        if target.account_name == "bad": raise RuntimeError("boom")
        return RssArticleCollectResult(1, 1, 0, 0, 1, None, None, False, 4, 200)
class Logs:
    def __init__(self): self.rows=[]
    def insert_collect_log(self, row): self.rows.append(row)

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
