from __future__ import annotations

from datetime import date, datetime

from app.domain.group_messages import GroupCursor, RawGroupMessage
from app.pipelines.article_interrupt_resume import ArticleCollectProgressRecord
from app.storage.article_log_repo import ArticleCollectLogRecord, MysqlArticleCollectLogRepo
from app.storage.article_progress_repo import MysqlArticleProgressRepo
from app.storage.article_raw_repo import MysqlArticleRawRepo, RawArticleRecord
from app.storage.article_route_cache_repo import MysqlArticleRouteCacheRepo
from app.storage.group_repo import (
    GroupCollectLogRecord,
    MysqlGroupCollectLogRepo,
    MysqlGroupMessageRepo,
)


class Result:
    def __init__(self, *, rows=None, rowcount=1) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self.executions = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FOR SHARE" in sql:
            return Result(
                rows=[{"id": 1, "source_name": self.source_name, "enabled": 1}]
            )
        if "SELECT 1" in sql and "wechat_article_raw" in sql:
            return Result(rows=[], rowcount=0)
        return Result()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, source_name: str) -> None:
        self.connection = Connection(source_name)
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


def _assert_first_history_lock(engine: Engine, table: str) -> None:
    assert engine.begin_count == 1
    sql, _ = engine.connection.executions[0]
    assert f"FROM {table}" in sql
    assert "FOR SHARE" in sql


def test_group_raw_and_cursor_lock_current_group_name_before_writing() -> None:
    raw_engine = Engine("核心群A")
    MysqlGroupMessageRepo(raw_engine).insert_raw_ignore_duplicates(
        [
            RawGroupMessage(
                msg_hash="h1",
                group_name="核心群A",
                sender_name="张三",
                msg_time_display="08:31",
                msg_type="text",
                msg_content="求购鸡蛋",
                raw_content="求购鸡蛋",
                collect_time=datetime(2026, 7, 2, 8, 33),
                collect_batch_id="batch-1",
            )
        ]
    )
    _assert_first_history_lock(raw_engine, "wechat_group_config")

    cursor_engine = Engine("核心群A")
    MysqlGroupMessageRepo(cursor_engine).update_cursor(
        GroupCursor(
            group_name="核心群A",
            last_msg_hash="h1",
            last_msg_time_display="08:31",
            last_msg_content_preview="求购鸡蛋",
            last_sender_name="张三",
            last_success_collect_time=datetime(2026, 7, 2, 8, 33),
            last_collect_batch_id="batch-1",
        )
    )
    _assert_first_history_lock(cursor_engine, "wechat_group_config")


def test_group_log_and_failure_cursor_lock_current_group_name_before_writing() -> None:
    log_engine = Engine("核心群A")
    MysqlGroupCollectLogRepo(log_engine).insert_collect_log(
        GroupCollectLogRecord(
            batch_id="batch-1",
            source_name="核心群A",
            start_time=datetime(2026, 7, 2, 8, 30),
            end_time=datetime(2026, 7, 2, 8, 31),
            status="success",
        )
    )
    _assert_first_history_lock(log_engine, "wechat_group_config")

    failure_engine = Engine("核心群A")
    MysqlGroupCollectLogRepo(failure_engine).mark_group_collect_failed(
        "核心群A", "boom"
    )
    _assert_first_history_lock(failure_engine, "wechat_group_config")


def test_article_route_cache_writes_lock_current_account_name() -> None:
    success_engine = Engine("行业观察")
    MysqlArticleRouteCacheRepo(success_engine).upsert_success(
        account_name="行业观察",
        route_type="bottom_menu",
        link_extract_type="copy_link_menu",
        entry_label=None,
        entry_index=None,
        success_time=datetime(2026, 7, 6, 8, 0),
    )
    _assert_first_history_lock(success_engine, "wechat_public_account_config")

    failure_engine = Engine("行业观察")
    MysqlArticleRouteCacheRepo(failure_engine).mark_failure(
        account_name="行业观察",
        error_code="FAILED",
        error_msg="boom",
        failure_time=datetime(2026, 7, 6, 8, 0),
        failure_threshold=3,
    )
    _assert_first_history_lock(failure_engine, "wechat_public_account_config")


def test_article_raw_and_collect_log_lock_current_account_name() -> None:
    raw_engine = Engine("行业观察")
    MysqlArticleRawRepo(raw_engine).insert_today_raw_ignore_duplicates(
        [
            RawArticleRecord(
                article_hash="a1",
                account_name="行业观察",
                title="今日文章",
                article_url="https://example.com/a",
                publish_time=datetime(2026, 7, 6, 8, 0),
                collect_time=datetime(2026, 7, 6, 8, 5),
            )
        ],
        crawl_date=date(2026, 7, 6),
    )
    _assert_first_history_lock(raw_engine, "wechat_public_account_config")

    log_engine = Engine("行业观察")
    MysqlArticleCollectLogRepo(log_engine).insert_collect_log(
        ArticleCollectLogRecord(
            batch_id="batch-1",
            account_name="行业观察",
            start_time=datetime(2026, 7, 6, 8, 0),
            end_time=datetime(2026, 7, 6, 8, 1),
            status="success",
        )
    )
    _assert_first_history_lock(log_engine, "wechat_public_account_config")


def test_article_raw_locks_multiple_accounts_in_stable_name_order() -> None:
    engine = Engine("账号")
    articles = [
        RawArticleRecord(
            article_hash=name,
            account_name=name,
            title="今日文章",
            article_url=f"https://example.com/{name}",
            publish_time=datetime(2026, 7, 6, 8, 0),
            collect_time=datetime(2026, 7, 6, 8, 5),
        )
        for name in ("B账号", "A账号")
    ]

    MysqlArticleRawRepo(engine).insert_today_raw_ignore_duplicates(
        articles, crawl_date=date(2026, 7, 6)
    )

    locks = [
        params["source_name"]
        for sql, params in engine.connection.executions
        if "FOR SHARE" in sql
    ]
    assert locks == ["A账号", "B账号"]


def test_article_progress_writes_lock_current_account_name() -> None:
    progress = ArticleCollectProgressRecord(
        crawl_date=date(2026, 7, 6),
        account_name="行业观察",
        stage="save_links",
        status="interrupted",
    )
    upsert_engine = Engine("行业观察")
    MysqlArticleProgressRepo(upsert_engine).upsert_progress(progress)
    _assert_first_history_lock(upsert_engine, "wechat_public_account_config")

    success_engine = Engine("行业观察")
    MysqlArticleProgressRepo(success_engine).mark_success(
        date(2026, 7, 6),
        "行业观察",
        success_time=datetime(2026, 7, 6, 9, 0),
    )
    _assert_first_history_lock(success_engine, "wechat_public_account_config")
