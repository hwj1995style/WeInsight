from __future__ import annotations

from datetime import date, datetime

from app.domain.group_messages import GroupCursor, RawGroupMessage
from app.storage.article_log_repo import ArticleCollectLogRecord, MysqlArticleCollectLogRepo
from app.storage.article_raw_repo import MysqlArticleRawRepo, RawArticleRecord
from app.storage.group_repo import GroupCollectLogRecord, MysqlGroupCollectLogRepo, MysqlGroupMessageRepo


class Result:
    def __init__(self, rows=None, rowcount=1): self.rows, self.rowcount = rows or [], rowcount
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, source_name): self.source_name, self.executions = source_name, []
    def execute(self, statement, params=None):
        sql = str(statement); self.executions.append((sql, params))
        if ("FROM wechat_group_config" in sql or "FROM wechat_public_account_config" in sql) and ("FOR SHARE" in sql or "FOR UPDATE" in sql):
            return Result([{"id": 1, "source_name": self.source_name, "enabled": 1}])
        if "SELECT 1" in sql and "wechat_article_raw" in sql: return Result([], 0)
        return Result()
    def __enter__(self): return self
    def __exit__(self, *args): return False


class Engine:
    def __init__(self, source_name): self.connection, self.begin_count = Connection(source_name), 0
    def begin(self): self.begin_count += 1; return self.connection


def _assert_first_history_lock(engine, table):
    assert engine.begin_count == 1
    assert f"FROM {table}" in engine.connection.executions[0][0]
    assert "FOR SHARE" in engine.connection.executions[0][0]


def test_group_raw_cursor_and_log_lock_current_group_before_writing():
    engine = Engine("核心群A")
    MysqlGroupMessageRepo(engine).insert_raw_ignore_duplicates([RawGroupMessage("h1", "核心群A", "张三", "08:31", "text", "求购", "求购", datetime(2026, 7, 2, 8, 33), "b1")])
    _assert_first_history_lock(engine, "wechat_group_config")
    cursor_engine = Engine("核心群A")
    MysqlGroupMessageRepo(cursor_engine).update_cursor(GroupCursor("核心群A", "h1", "08:31", "求购", "张三", datetime(2026, 7, 2, 8, 33), "b1"))
    _assert_first_history_lock(cursor_engine, "wechat_group_config")
    log_engine = Engine("核心群A")
    MysqlGroupCollectLogRepo(log_engine).insert_collect_log(GroupCollectLogRecord("b1", "核心群A", datetime(2026,7,2,8,30), datetime(2026,7,2,8,31), "success"))
    _assert_first_history_lock(log_engine, "wechat_group_config")


def test_rss_article_raw_and_collect_log_lock_current_account_before_writing():
    raw_engine = Engine("行业观察")
    MysqlArticleRawRepo(raw_engine).insert_today_raw_ignore_duplicates([RawArticleRecord("a1", "行业观察", "今日文章", "https://example.com/a", datetime(2026,7,6,8), datetime(2026,7,6,8,5))], crawl_date=date(2026,7,6))
    _assert_first_history_lock(raw_engine, "wechat_public_account_config")
    log_engine = Engine("行业观察")
    MysqlArticleCollectLogRepo(log_engine).insert_collect_log(ArticleCollectLogRecord("b1", "行业观察", datetime(2026,7,6,8), datetime(2026,7,6,8,1), "success"))
    _assert_first_history_lock(log_engine, "wechat_public_account_config")


def test_werss_sync_source_never_deletes_history_or_task_references():
    from pathlib import Path

    source = Path("app/storage/werss_catalog_sync_repo.py").read_text(encoding="utf-8").upper()
    assert "DELETE FROM" not in source
    assert "TRUNCATE TABLE" not in source
