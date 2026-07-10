from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from app.pipelines.article_collect_service import ArticleCollectService
from app.pipelines.article_core_group_due_provider import ReadOnlyCoreGroupDueProvider
from app.pipelines.article_interrupt_resume import ArticleCollectProgressRecord
from app.pipelines.article_pipeline import ArticlePipelineState
from app.pipelines.article_polling_runner import ArticlePollingRunner, ArticlePollingTarget
from app.pipelines.group_pipeline import GroupPipelineState
from app.rpa.fake_clients import FakeArticleRpaClient
from app.storage.article_raw_repo import ArticleRawInsertResult
from app.storage.lock_repo import InMemoryUiLockRepo


def test_init_sql_has_separate_group_and_article_tables() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_group_process_task" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_article_process_task" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_collect_log" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_article_collect_log" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_article_collect_progress" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_ui_lock" in sql


def test_pipeline_state_is_separate() -> None:
    group_state = GroupPipelineState(pending_tasks=2, failed_tasks=0)
    article_state = ArticlePipelineState(pending_tasks=5, failed_tasks=1)

    article_state = article_state.mark_failed()

    assert group_state.failed_tasks == 0
    assert article_state.failed_tasks == 2


class SpyGroupConfigRepo:
    def __init__(self) -> None:
        self.read_count = 0
        self.write_count = 0

    def list_due_groups(self, now: datetime, limit: int):
        self.read_count += 1
        assert limit == 1
        return [object()]

    def upsert_group_config(self, *args, **kwargs) -> None:
        self.write_count += 1

    def disable_group(self, *args, **kwargs) -> None:
        self.write_count += 1


class FakeArticleRawRepo:
    def insert_today_raw_ignore_duplicates(self, articles, *, crawl_date: date) -> ArticleRawInsertResult:
        article_list = list(articles)
        return ArticleRawInsertResult(
            read_count=len(article_list),
            inserted_count=len(article_list),
            duplicate_count=0,
            skipped_count=0,
            task_created_count=len(article_list),
        )


class FakeArticleProgressRepo:
    def __init__(self) -> None:
        self.upserts: list[ArticleCollectProgressRecord] = []

    def get_progress(self, crawl_date: date, account_name: str):
        return None

    def upsert_progress(self, record: ArticleCollectProgressRecord) -> None:
        self.upserts.append(record)

    def mark_success(
        self,
        crawl_date: date,
        account_name: str,
        success_time: datetime | None = None,
    ) -> None:
        raise AssertionError("interrupted article run must not mark progress success")


class FakeArticleLogRepo:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def insert_collect_log(self, record) -> None:
        self.records.append(record.__dict__)


class FakeScreenshotClient:
    def save_screenshot(self, path: str) -> str:
        return path


def test_article_scheduler_interruption_does_not_modify_group_repositories() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    group_repo = SpyGroupConfigRepo()
    progress_repo = FakeArticleProgressRepo()
    log_repo = FakeArticleLogRepo()
    due_provider = ReadOnlyCoreGroupDueProvider(
        group_config_repo=group_repo,
        poll_interval_seconds=30,
        now_provider=lambda: now,
    )
    runner = ArticlePollingRunner(
        collect_service=ArticleCollectService(
            rpa=FakeArticleRpaClient(
                links_by_account={
                    "行业观察": ["https://mp.weixin.qq.com/s/1"],
                }
            ),
            raw_repo=FakeArticleRawRepo(),
        ),
        lock_repo=InMemoryUiLockRepo(),
        account_provider=lambda current, limit: [
            ArticlePollingTarget("行业观察", priority=1, poll_interval_minutes=60, max_articles_per_round=1)
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-isolation",
        progress_repo=progress_repo,
        next_core_group_due_provider=due_provider,
        max_core_group_block_seconds=10,
    )

    result = runner.run_once(now)

    assert result.interrupted_count == 1
    assert group_repo.read_count >= 1
    assert group_repo.write_count == 0
    assert progress_repo.upserts[0].account_name == "行业观察"
    assert progress_repo.upserts[0].status == "interrupted"
    assert log_repo.records[0]["status"] == "interrupted"
