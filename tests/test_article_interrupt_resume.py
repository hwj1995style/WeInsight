from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from app.pipelines.article_collect_service import ArticleCollectService
from app.pipelines.article_interrupt_resume import (
    ArticleCollectProgressRecord,
    core_group_block_seconds,
    should_interrupt_article_for_core_group,
)
from app.pipelines.article_pipeline import ArticleStage, ArticleUiDecision
from app.pipelines.article_polling_runner import ArticlePollingRunner, ArticlePollingTarget
from app.rpa.fake_clients import FakeArticleRpaClient
from app.storage.article_raw_repo import ArticleRawInsertResult
from app.storage.lock_repo import InMemoryUiLockRepo


class FakeArticleRawRepo:
    def __init__(self) -> None:
        self.articles = []

    def insert_today_raw_ignore_duplicates(self, articles, *, crawl_date: date) -> ArticleRawInsertResult:
        self.articles.extend(list(articles))
        return ArticleRawInsertResult(
            read_count=len(self.articles),
            inserted_count=len(self.articles),
            duplicate_count=0,
            skipped_count=0,
            task_created_count=len(self.articles),
        )


class FakeArticleProgressRepo:
    def __init__(self, progress=None) -> None:
        self.progress = progress
        self.upserts: list[ArticleCollectProgressRecord] = []
        self.successes: list[tuple[date, str, datetime | None]] = []

    def get_progress(self, crawl_date: date, account_name: str):
        if self.progress is None:
            return None
        if self.progress.crawl_date == crawl_date and self.progress.account_name == account_name:
            return self.progress
        return None

    def upsert_progress(self, record: ArticleCollectProgressRecord) -> None:
        self.progress = record
        self.upserts.append(record)

    def mark_success(
        self,
        crawl_date: date,
        account_name: str,
        success_time: datetime | None = None,
    ) -> None:
        self.successes.append((crawl_date, account_name, success_time))


class FakeArticleLogRepo:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def insert_collect_log(self, record) -> None:
        self.records.append(record.__dict__)


class FakeScreenshotClient:
    def save_screenshot(self, path: str) -> str:
        return path


class SequenceCoreDueProvider:
    def __init__(self, values) -> None:
        self.values = list(values)

    def __call__(self):
        if not self.values:
            return None
        return self.values.pop(0)


def _runner(
    *,
    service: ArticleCollectService,
    lock_repo: InMemoryUiLockRepo,
    progress_repo: FakeArticleProgressRepo,
    log_repo: FakeArticleLogRepo,
    next_core_group_due_provider,
    max_core_group_block_seconds: int = 10,
) -> ArticlePollingRunner:
    return ArticlePollingRunner(
        collect_service=service,
        lock_repo=lock_repo,
        account_provider=lambda current, limit: [
            ArticlePollingTarget("行业观察", priority=1, poll_interval_minutes=60, max_articles_per_round=5)
        ],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda account_name: "article-batch-1",
        progress_repo=progress_repo,
        next_core_group_due_provider=next_core_group_due_provider,
        max_core_group_block_seconds=max_core_group_block_seconds,
    )


def test_article_runner_interrupts_at_safe_checkpoint_and_releases_ui_lock() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    raw_repo = FakeArticleRawRepo()
    service = ArticleCollectService(
        rpa=FakeArticleRpaClient(
            links_by_account={
                "行业观察": [
                    "https://mp.weixin.qq.com/s/1",
                    "https://mp.weixin.qq.com/s/2",
                ]
            }
        ),
        raw_repo=raw_repo,
    )
    lock_repo = InMemoryUiLockRepo()
    progress_repo = FakeArticleProgressRepo()
    log_repo = FakeArticleLogRepo()
    next_core_group_due_provider = SequenceCoreDueProvider(
        [
            now + timedelta(seconds=60),
            now + timedelta(seconds=60),
            now,
        ]
    )

    result = _runner(
        service=service,
        lock_repo=lock_repo,
        progress_repo=progress_repo,
        log_repo=log_repo,
        next_core_group_due_provider=next_core_group_due_provider,
    ).run_once(now)

    assert result.attempted_count == 1
    assert result.interrupted_count == 1
    assert result.success_count == 0
    assert lock_repo.current_owner("wechat_ui") is None
    assert [article.article_url for article in raw_repo.articles] == [
        "https://mp.weixin.qq.com/s/1",
        "https://mp.weixin.qq.com/s/2",
    ]
    assert progress_repo.upserts[0].crawl_date == date(2026, 7, 6)
    assert progress_repo.upserts[0].account_name == "行业观察"
    assert progress_repo.upserts[0].stage == ArticleStage.SAVE_LINKS.value
    assert progress_repo.upserts[0].status == "interrupted"
    assert progress_repo.upserts[0].last_article_url == "https://mp.weixin.qq.com/s/2"
    assert log_repo.records[0]["status"] == "interrupted"
    assert log_repo.records[0]["error_code"] == "ARTICLE_INTERRUPTED_FOR_CORE_GROUP"


def test_article_runner_resumes_after_last_saved_article_url() -> None:
    now = datetime(2026, 7, 6, 10, 0)
    raw_repo = FakeArticleRawRepo()
    service = ArticleCollectService(
        rpa=FakeArticleRpaClient(
            links_by_account={
                "行业观察": [
                    "https://mp.weixin.qq.com/s/1",
                    "https://mp.weixin.qq.com/s/2",
                    "https://mp.weixin.qq.com/s/3",
                ]
            }
        ),
        raw_repo=raw_repo,
    )
    progress_repo = FakeArticleProgressRepo(
        ArticleCollectProgressRecord(
            crawl_date=date(2026, 7, 6),
            account_name="行业观察",
            stage=ArticleStage.SAVE_LINKS.value,
            status="interrupted",
            last_article_url="https://mp.weixin.qq.com/s/1",
            retry_count=1,
        )
    )
    log_repo = FakeArticleLogRepo()

    result = _runner(
        service=service,
        lock_repo=InMemoryUiLockRepo(),
        progress_repo=progress_repo,
        log_repo=log_repo,
        next_core_group_due_provider=lambda: now + timedelta(seconds=60),
    ).run_once(now)

    assert result.success_count == 1
    assert result.interrupted_count == 0
    assert [article.article_url for article in raw_repo.articles] == [
        "https://mp.weixin.qq.com/s/2",
        "https://mp.weixin.qq.com/s/3",
    ]
    assert progress_repo.successes == [(date(2026, 7, 6), "行业观察", now)]
    assert log_repo.records[0]["status"] == "success"


def test_article_core_group_block_threshold_policy() -> None:
    next_core_group_due = datetime(2026, 7, 6, 9, 0)
    checkpoint_time = next_core_group_due + timedelta(seconds=9)

    assert (
        should_interrupt_article_for_core_group(
            checkpoint_time=checkpoint_time,
            next_core_group_due=next_core_group_due,
        )
        == ArticleUiDecision.DEFER
    )
    assert core_group_block_seconds(checkpoint_time, next_core_group_due) <= 10


def test_mysql_article_progress_repo_writes_article_progress_without_group_tables() -> None:
    from app.storage.article_progress_repo import MysqlArticleProgressRepo

    class FakeResult:
        def __init__(self, rows=None) -> None:
            self._rows = rows or []
            self.rowcount = 1

        def mappings(self):
            return self

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeConnection:
        def __init__(self) -> None:
            self.executions: list[tuple[str, object]] = []

        def execute(self, statement, params=None):
            sql = str(statement)
            self.executions.append((sql, params))
            if "FOR SHARE" in sql or "FOR UPDATE" in sql:
                return FakeResult(
                    rows=[
                        {
                            "id": 9,
                            "source_name": "行业观察",
                            "enabled": 1,
                        }
                    ]
                )
            if "SELECT" in sql:
                return FakeResult(
                    rows=[
                        {
                            "crawl_date": date(2026, 7, 6),
                            "account_name": "行业观察",
                            "stage": "save_links",
                            "last_article_url": "https://mp.weixin.qq.com/s/1",
                            "status": "interrupted",
                            "retry_count": 1,
                            "last_error_code": "ARTICLE_INTERRUPTED_FOR_CORE_GROUP",
                            "last_error_msg": "core group due",
                        }
                    ]
                )
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def __init__(self) -> None:
            self.connection = FakeConnection()

        def begin(self):
            return self.connection

    engine = FakeEngine()
    repo = MysqlArticleProgressRepo(engine)
    progress = ArticleCollectProgressRecord(
        crawl_date=date(2026, 7, 6),
        account_name="行业观察",
        stage="save_links",
        status="interrupted",
        last_article_url="https://mp.weixin.qq.com/s/1",
        retry_count=1,
        last_error_code="ARTICLE_INTERRUPTED_FOR_CORE_GROUP",
        last_error_msg="core group due",
    )

    repo.upsert_progress(progress)
    loaded = repo.get_progress(date(2026, 7, 6), "行业观察")
    success_time = datetime(2026, 7, 6, 9, 0)
    repo.mark_success(date(2026, 7, 6), "行业观察", success_time=success_time)

    executed_sql = "\n".join(sql for sql, _ in engine.connection.executions)
    assert "wechat_article_collect_progress" in executed_sql
    assert "UPDATE wechat_public_account_config" in executed_sql
    assert "last_success_collect_time = :success_time" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert "wechat_group_" not in executed_sql
    assert loaded == progress
    assert engine.connection.executions[-1][1] == {
        "account_name": "行业观察",
        "success_time": success_time,
    }
