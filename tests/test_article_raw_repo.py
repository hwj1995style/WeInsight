from __future__ import annotations

from datetime import date, datetime

from app.domain.hashes import article_hash
from app.storage.article_raw_repo import (
    MysqlArticleRawRepo,
    RawArticleRecord,
)


class FakeResult:
    def __init__(self, rowcount: int = 0, rows=None) -> None:
        self.rowcount = rowcount
        self._rows = rows or []

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self


class FakeConnection:
    def __init__(self, rowcounts: list[int], existing_url_results=None) -> None:
        self.rowcounts = list(rowcounts)
        self.existing_url_results = list(existing_url_results or [])
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FOR SHARE" in sql:
            return FakeResult(
                rowcount=1,
                rows=[{"id": 9, "source_name": "行业观察", "enabled": 1}],
            )
        if "SELECT 1" in sql and "wechat_article_raw" in sql:
            rows = self.existing_url_results.pop(0) if self.existing_url_results else []
            return FakeResult(rowcount=len(rows), rows=rows)
        rowcount = self.rowcounts.pop(0) if self.rowcounts else 0
        return FakeResult(rowcount)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rowcounts: list[int], existing_url_results=None) -> None:
        self.connection = FakeConnection(rowcounts, existing_url_results=existing_url_results)

    def begin(self):
        return self.connection


def test_mysql_article_raw_repo_inserts_today_articles_and_creates_clean_task() -> None:
    crawl_date = date(2026, 7, 6)
    today_publish_time = datetime(2026, 7, 6, 8, 0)
    collect_time = datetime(2026, 7, 6, 8, 5)
    today = RawArticleRecord(
        article_hash=article_hash(
            account_name="行业观察",
            title="今日文章",
            publish_time=today_publish_time,
            url="https://example.com/a",
        ),
        account_name="行业观察",
        title="今日文章",
        article_url="https://example.com/a",
        publish_time=today_publish_time,
        author="作者",
        digest="摘要",
        collect_batch_id="batch-1",
        collect_time=collect_time,
    )
    yesterday = RawArticleRecord(
        article_hash=article_hash(
            account_name="行业观察",
            title="昨日文章",
            publish_time=datetime(2026, 7, 5, 23, 59),
            url="https://example.com/b",
        ),
        account_name="行业观察",
        title="昨日文章",
        article_url="https://example.com/b",
        publish_time=datetime(2026, 7, 5, 23, 59),
        collect_time=collect_time,
    )
    unknown_time = RawArticleRecord(
        article_hash=article_hash(
            account_name="行业观察",
            title="未知时间",
            publish_time=None,
            url="https://example.com/c",
        ),
        account_name="行业观察",
        title="未知时间",
        article_url="https://example.com/c",
        publish_time=None,
        collect_time=collect_time,
    )
    engine = FakeEngine(rowcounts=[1, 1])
    repo = MysqlArticleRawRepo(engine)

    result = repo.insert_today_raw_ignore_duplicates([today, yesterday, unknown_time], crawl_date=crawl_date)

    assert result.read_count == 3
    assert result.inserted_count == 1
    assert result.duplicate_count == 0
    assert result.skipped_count == 2
    assert result.task_created_count == 1
    assert len(engine.connection.executions) == 4

    duplicate_sql, duplicate_params = engine.connection.executions[1]
    raw_sql, raw_params = engine.connection.executions[2]
    task_sql, task_params = engine.connection.executions[3]
    assert "SELECT 1" in duplicate_sql
    assert duplicate_params["account_name"] == "行业观察"
    assert duplicate_params["publish_date"] == crawl_date
    assert duplicate_params["article_url"] == "https://example.com/a"

    assert "INSERT IGNORE INTO wechat_article_raw" in raw_sql
    assert "wechat_group_" not in raw_sql
    assert raw_params["article_hash"] == today.article_hash
    assert raw_params["publish_date"] == crawl_date
    assert raw_params["collect_batch_id"] == "batch-1"

    assert "INSERT IGNORE INTO wechat_article_process_task" in task_sql
    assert "wechat_group_" not in task_sql
    assert task_params["task_type"] == "clean_article"
    assert task_params["ref_type"] == "article"
    assert task_params["ref_id"] == today.article_hash


def test_mysql_article_raw_repo_does_not_create_task_for_duplicate_article() -> None:
    publish_time = datetime(2026, 7, 6, 8, 0)
    article = RawArticleRecord(
        article_hash=article_hash(
            account_name="行业观察",
            title="重复文章",
            publish_time=publish_time,
            url="https://example.com/duplicate",
        ),
        account_name="行业观察",
        title="重复文章",
        article_url="https://example.com/duplicate",
        publish_time=publish_time,
        collect_time=datetime(2026, 7, 6, 8, 5),
    )
    engine = FakeEngine(rowcounts=[0])
    repo = MysqlArticleRawRepo(engine)

    result = repo.insert_today_raw_ignore_duplicates([article], crawl_date=date(2026, 7, 6))

    assert result.read_count == 1
    assert result.inserted_count == 0
    assert result.duplicate_count == 1
    assert result.skipped_count == 0
    assert result.task_created_count == 0
    assert len(engine.connection.executions) == 3


def test_mysql_article_raw_repo_treats_existing_account_day_url_as_duplicate() -> None:
    publish_time = datetime(2026, 7, 6, 8, 0)
    article = RawArticleRecord(
        article_hash="different-hash-for-same-url",
        account_name="行业观察",
        title="重复文章",
        article_url="https://example.com/duplicate-url",
        publish_time=publish_time,
        collect_time=datetime(2026, 7, 6, 9, 5),
    )
    engine = FakeEngine(rowcounts=[1, 1], existing_url_results=[[(1,)]])
    repo = MysqlArticleRawRepo(engine)

    result = repo.insert_today_raw_ignore_duplicates([article], crawl_date=date(2026, 7, 6))

    assert result.read_count == 1
    assert result.inserted_count == 0
    assert result.duplicate_count == 1
    assert result.skipped_count == 0
    assert result.task_created_count == 0
    assert len(engine.connection.executions) == 2
    duplicate_sql, duplicate_params = engine.connection.executions[1]
    assert "SELECT 1" in duplicate_sql
    assert duplicate_params["account_name"] == "行业观察"
    assert duplicate_params["publish_date"] == date(2026, 7, 6)
    assert duplicate_params["article_url"] == "https://example.com/duplicate-url"


def test_mysql_article_raw_repo_sql_is_isolated_from_group_tables() -> None:
    publish_time = datetime(2026, 7, 6, 8, 0)
    article = RawArticleRecord(
        article_hash=article_hash(
            account_name="行业观察",
            title="隔离验证",
            publish_time=publish_time,
            url="https://example.com/isolated",
        ),
        account_name="行业观察",
        title="隔离验证",
        article_url="https://example.com/isolated",
        publish_time=publish_time,
        collect_time=datetime(2026, 7, 6, 8, 5),
    )
    engine = FakeEngine(rowcounts=[1, 1])
    repo = MysqlArticleRawRepo(engine)

    repo.insert_today_raw_ignore_duplicates([article], crawl_date=date(2026, 7, 6))

    executed_sql = "\n".join(sql for sql, _ in engine.connection.executions)
    assert "wechat_article_raw" in executed_sql
    assert "wechat_article_process_task" in executed_sql
    assert "wechat_group_" not in executed_sql


def test_insert_raw_accepts_historical_article_and_checks_hash_and_account_url() -> None:
    article = RawArticleRecord(
        article_hash="historical-hash",
        account_name="行业观察",
        title="旧标题",
        article_url="https://mp.weixin.qq.com/s/a?a=1&b=2",
        publish_time=datetime(2020, 1, 2, 3, 4),
        collect_time=datetime(2026, 7, 11, 8),
    )
    engine = FakeEngine(rowcounts=[1, 1])

    result = MysqlArticleRawRepo(engine).insert_raw_ignore_duplicates([article])

    assert result.inserted_count == 1
    assert result.skipped_count == 0
    duplicate_sql, params = engine.connection.executions[1]
    assert "article_hash = :article_hash" in duplicate_sql
    assert "account_name = :account_name" in duplicate_sql
    assert "article_url = :article_url" in duplicate_sql
    assert "publish_date" not in duplicate_sql
    assert params["article_hash"] == "historical-hash"


def test_insert_raw_skips_same_account_normalized_url_with_changed_title() -> None:
    article = RawArticleRecord(
        article_hash="new-title-hash",
        account_name="行业观察",
        title="新标题",
        article_url="https://mp.weixin.qq.com/s/a?a=1&b=2",
        publish_time=datetime(2026, 7, 11, 8),
        collect_time=datetime(2026, 7, 11, 9),
    )
    engine = FakeEngine(rowcounts=[], existing_url_results=[[(1,)]])

    result = MysqlArticleRawRepo(engine).insert_raw_ignore_duplicates([article])

    assert result.inserted_count == 0
    assert result.duplicate_count == 1
    assert result.task_created_count == 0
    assert len(engine.connection.executions) == 2
