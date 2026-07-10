from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.pipelines.article_collect_service import ArticleCollectResult
from app.pipelines.article_polling_runner import ArticlePollingRunner, ArticlePollingTarget
from app.storage.lock_repo import InMemoryUiLockRepo


class FakeArticleCollectService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime, int]] = []
        self.fail_with: Exception | None = None
        self.result = ArticleCollectResult(
            account_name="账号B",
            batch_id="article-账号B",
            link_count=2,
            insert_count=1,
            duplicate_count=1,
            skipped_count=0,
            task_created_count=1,
        )

    def collect_once(
        self,
        *,
        account_name: str,
        batch_id: str,
        collect_time: datetime,
        max_articles: int,
    ) -> ArticleCollectResult:
        self.calls.append((account_name, batch_id, collect_time, max_articles))
        if self.fail_with is not None:
            raise self.fail_with
        return self.result


class FakeArticleLogRepo:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def insert_collect_log(self, record) -> None:
        self.records.append(record.__dict__)


class FakeScreenshotClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def save_screenshot(self, path: str) -> str:
        self.paths.append(path)
        return path


class FakeArticleProgressRepo:
    def __init__(self) -> None:
        self.successes: list[tuple[datetime, str, datetime | None]] = []

    def get_progress(self, crawl_date, account_name: str):
        return None

    def mark_success(self, crawl_date, account_name: str, success_time: datetime | None = None) -> None:
        self.successes.append((crawl_date, account_name, success_time))


def test_article_polling_runner_processes_one_due_account_with_ui_lock() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeArticleCollectService()
    log_repo = FakeArticleLogRepo()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号B", priority=1, poll_interval_minutes=60, max_articles_per_round=5),
            ArticlePollingTarget("账号A", priority=2, poll_interval_minutes=60, max_articles_per_round=5),
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: f"article-{account_name}",
    )

    result = runner.run_once(now)

    assert result.attempted_count == 1
    assert result.success_count == 1
    assert result.error_code is None
    assert result.screenshot_path is None
    assert collect_service.calls == [("账号B", "article-账号B", now, 5)]
    assert lock_repo.current_owner("wechat_ui") is None
    assert len(log_repo.records) == 1
    assert log_repo.records[0]["account_name"] == "账号B"
    assert log_repo.records[0]["status"] == "success"
    assert log_repo.records[0]["stage"] == "save_links"
    assert log_repo.records[0]["link_count"] == 2
    assert log_repo.records[0]["insert_count"] == 1


def test_article_polling_runner_marks_article_account_success_time() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeArticleCollectService()
    progress_repo = FakeArticleProgressRepo()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号B", priority=1, poll_interval_minutes=60, max_articles_per_round=5)
        ],
        log_repo=FakeArticleLogRepo(),
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: f"article-{account_name}",
        progress_repo=progress_repo,
    )

    result = runner.run_once(now)

    assert result.success_count == 1
    assert progress_repo.successes == [(now.date(), "账号B", now)]


def test_article_polling_runner_does_not_open_article_when_group_holds_ui_lock() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    assert lock_repo.acquire("wechat_ui", "group", "group-batch", now, 120) is True
    collect_service = FakeArticleCollectService()
    log_repo = FakeArticleLogRepo()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号A", priority=1, poll_interval_minutes=60, max_articles_per_round=5)
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-lock-timeout",
    )

    result = runner.run_once(now)

    assert result.lock_timeout_count == 1
    assert result.error_code == "WECHAT_UI_LOCK_TIMEOUT"
    assert result.error_summary is not None
    assert collect_service.calls == []
    assert lock_repo.current_owner("wechat_ui") == "group"
    assert log_repo.records[0]["status"] == "failed"
    assert log_repo.records[0]["error_code"] == "WECHAT_UI_LOCK_TIMEOUT"


def test_article_polling_runner_saves_screenshot_and_releases_lock_on_rpa_error() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeArticleCollectService()
    collect_service.fail_with = RuntimeError("article boom")
    log_repo = FakeArticleLogRepo()
    screenshot_client = FakeScreenshotClient()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号A", priority=1, poll_interval_minutes=60, max_articles_per_round=5)
        ],
        log_repo=log_repo,
        screenshot_client=screenshot_client,
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-error",
    )

    result = runner.run_once(now)

    assert result.failed_count == 1
    assert result.error_code == "WECHAT_ARTICLE_RPA_ERROR"
    assert result.error_summary == "article boom"
    assert result.screenshot_path == screenshot_client.paths[0]
    assert lock_repo.current_owner("wechat_ui") is None
    assert screenshot_client.paths == ["runtime/screenshots/article/20260706/article-error.png"]
    assert log_repo.records[0]["status"] == "failed"
    assert log_repo.records[0]["stage"] == "copy_links"
    assert log_repo.records[0]["error_code"] == "WECHAT_ARTICLE_RPA_ERROR"
    assert log_repo.records[0]["screenshot_path"] == screenshot_client.paths[0]


def test_article_polling_runner_treats_no_copied_links_as_no_data_skip() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeArticleCollectService()
    collect_service.result = ArticleCollectResult(
        account_name="账号A",
        batch_id="article-no-links",
        link_count=0,
        insert_count=0,
        duplicate_count=0,
        skipped_count=0,
        task_created_count=0,
    )
    log_repo = FakeArticleLogRepo()
    progress_repo = FakeArticleProgressRepo()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号A", priority=1, poll_interval_minutes=60, max_articles_per_round=1)
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-no-links",
        progress_repo=progress_repo,
    )

    result = runner.run_once(now)

    assert result.success_count == 0
    assert result.failed_count == 0
    assert result.skipped_count == 1
    assert result.link_count == 0
    assert result.raw_insert_count == 0
    assert result.duplicate_count == 0
    assert result.task_created_count == 0
    assert result.error_code == "WECHAT_ARTICLE_NO_TODAY_ARTICLE"
    assert progress_repo.successes == [(now.date(), "账号A", now)]
    assert log_repo.records[0]["status"] == "skipped"
    assert log_repo.records[0]["stage"] == "copy_links"
    assert log_repo.records[0]["error_code"] == "WECHAT_ARTICLE_NO_TODAY_ARTICLE"
    assert log_repo.records[0]["link_count"] == 0
    assert log_repo.records[0]["insert_count"] == 0


def test_article_polling_runner_requires_raw_insert_or_duplicate_evidence() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeArticleCollectService()
    collect_service.result = ArticleCollectResult(
        account_name="账号A",
        batch_id="article-no-raw",
        link_count=1,
        insert_count=0,
        duplicate_count=0,
        skipped_count=0,
        task_created_count=0,
    )
    log_repo = FakeArticleLogRepo()
    runner = ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("账号A", priority=1, poll_interval_minutes=60, max_articles_per_round=1)
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-no-raw",
    )

    result = runner.run_once(now)

    assert result.success_count == 0
    assert result.failed_count == 1
    assert result.link_count == 1
    assert result.raw_insert_count == 0
    assert result.duplicate_count == 0
    assert result.error_code == "WECHAT_ARTICLE_NO_RAW_EVIDENCE"
    assert log_repo.records[0]["status"] == "failed"
    assert log_repo.records[0]["error_code"] == "WECHAT_ARTICLE_NO_RAW_EVIDENCE"
