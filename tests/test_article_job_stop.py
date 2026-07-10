from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from app.pipelines.article_collect_service import ArticleCollectService
from app.pipelines.article_interrupt_resume import ArticleCollectProgressRecord
from app.pipelines.article_polling_runner import (
    ArticlePollingRunner,
    ArticlePollingTarget,
)
from app.rpa.fake_clients import FakeArticleRpaClient
from app.storage.article_raw_repo import ArticleRawInsertResult
from app.storage.lock_repo import InMemoryUiLockRepo


NOW = datetime(2026, 7, 10, 9, 30)


class RawRepo:
    def insert_today_raw_ignore_duplicates(
        self, articles, *, crawl_date: date
    ) -> ArticleRawInsertResult:
        rows = list(articles)
        return ArticleRawInsertResult(
            read_count=len(rows),
            inserted_count=len(rows),
            duplicate_count=0,
            skipped_count=0,
            task_created_count=len(rows),
        )


class ProgressRepo:
    def __init__(self, *, fail_upsert: bool = False) -> None:
        self.upserts: list[ArticleCollectProgressRecord] = []
        self.fail_upsert = fail_upsert

    def get_progress(self, crawl_date, account_name):
        return None

    def upsert_progress(self, record) -> None:
        if self.fail_upsert:
            raise RuntimeError("progress unavailable")
        self.upserts.append(record)

    def mark_success(self, crawl_date, account_name, success_time=None) -> None:
        raise AssertionError("stop must not mark success")


class LogRepo:
    def __init__(self) -> None:
        self.records = []

    def insert_collect_log(self, record) -> None:
        self.records.append(record)


class ScreenshotClient:
    def __init__(self) -> None:
        self.paths = []

    def save_screenshot(self, path: str) -> str:
        self.paths.append(path)
        return path


class StopAtCall:
    def __init__(self, call: int) -> None:
        self.call = call
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls >= self.call


def build_runner(stop_provider, progress_repo, lock_repo, log_repo, screenshots):
    service = ArticleCollectService(
        rpa=FakeArticleRpaClient(
            {"行业观察": ["https://mp.weixin.qq.com/s/article-1"]}
        ),
        raw_repo=RawRepo(),
    )
    return ArticlePollingRunner(
        collect_service=service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("行业观察", 1, 10, 1)
        ],
        log_repo=log_repo,
        screenshot_client=screenshots,
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account: "article-stop-batch",
        progress_repo=progress_repo,
        next_core_group_due_provider=None,
        stop_requested_provider=stop_provider,
    )


@pytest.mark.parametrize(
    ("stop_call", "stage", "last_url"),
    [
        (1, "open_account", None),
        (2, "copy_links", None),
        (3, "save_links", "https://mp.weixin.qq.com/s/article-1"),
    ],
)
def test_article_stop_requested_interrupts_at_each_safe_checkpoint(
    stop_call, stage, last_url
) -> None:
    stop = StopAtCall(stop_call)
    progress = ProgressRepo()
    lock_repo = InMemoryUiLockRepo()
    log_repo = LogRepo()
    screenshots = ScreenshotClient()
    runner = build_runner(stop, progress, lock_repo, log_repo, screenshots)

    result = runner.run_once(NOW)

    assert result.interrupted_count == 1
    assert result.stop_requested_count == 1
    assert result.core_group_interrupted_count == 0
    assert result.error_code == "ARTICLE_STOP_REQUESTED"
    assert result.screenshot_path is None
    assert screenshots.paths == []
    assert lock_repo.current_owner("wechat_ui") is None
    assert len(progress.upserts) == 1
    saved = progress.upserts[0]
    assert saved.stage == stage
    assert saved.status == "interrupted"
    assert saved.last_article_url == last_url
    assert saved.last_error_code == "ARTICLE_STOP_REQUESTED"
    assert log_repo.records[0].status == "interrupted"
    assert log_repo.records[0].error_code == "ARTICLE_STOP_REQUESTED"


def test_stop_check_runs_before_core_group_check() -> None:
    progress = ProgressRepo()
    lock_repo = InMemoryUiLockRepo()
    log_repo = LogRepo()
    screenshots = ScreenshotClient()
    runner = build_runner(
        lambda: True, progress, lock_repo, log_repo, screenshots
    )
    runner.next_core_group_due_provider = lambda: (_ for _ in ()).throw(
        AssertionError("core provider must not run after job stop")
    )

    result = runner.run_once(NOW)

    assert result.stop_requested_count == 1
    assert result.failed_count == 0


@pytest.mark.parametrize(
    "stop_provider,progress_repo",
    [
        (lambda: (_ for _ in ()).throw(RuntimeError("stop db down")), ProgressRepo()),
        (lambda: True, ProgressRepo(fail_upsert=True)),
    ],
)
def test_stop_provider_or_progress_error_fails_closed(
    stop_provider, progress_repo
) -> None:
    lock_repo = InMemoryUiLockRepo()
    log_repo = LogRepo()
    screenshots = ScreenshotClient()
    runner = build_runner(
        stop_provider, progress_repo, lock_repo, log_repo, screenshots
    )

    result = runner.run_once(NOW)

    assert result.success_count == 0
    assert result.failed_count == 1
    assert lock_repo.current_owner("wechat_ui") is None
