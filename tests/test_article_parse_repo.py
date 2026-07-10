from __future__ import annotations

from datetime import datetime

from app.domain.article_parsing import CleanArticleRecord
from app.storage.article_parse_repo import MysqlArticleParseRepo


class FakeResult:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "SELECT" in sql:
            return FakeResult(self.rows)
        return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rows=None) -> None:
        self.connection = FakeConnection(rows)

    def begin(self):
        return self.connection


def test_mysql_article_parse_repo_lists_pending_article_tasks_without_group_tables() -> None:
    engine = FakeEngine(
        rows=[
            {
                "article_hash": "article-hash-1",
                "account_name": "行业观察",
                "title": "raw title",
                "article_url": "https://mp.weixin.qq.com/s/abc",
                "publish_time": datetime(2026, 7, 6, 8, 0),
                "author": None,
                "digest": None,
            }
        ]
    )
    repo = MysqlArticleParseRepo(engine)

    articles = repo.list_pending_parse_articles(limit=5)

    assert articles[0].article_hash == "article-hash-1"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_process_task" in sql
    assert "JOIN wechat_article_raw" in sql
    assert "task.task_type = 'clean_article'" in sql
    assert "task.status = 'pending'" in sql
    assert "wechat_group_" not in sql
    assert params["limit"] == 5


def test_mysql_article_parse_repo_writes_clean_article_and_updates_article_tasks_only() -> None:
    engine = FakeEngine()
    repo = MysqlArticleParseRepo(engine)
    article = CleanArticleRecord(
        article_hash="article-hash-1",
        account_name="行业观察",
        title="解析标题",
        article_url="https://mp.weixin.qq.com/s/abc",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author="作者",
        digest="摘要",
        content_length=88,
        parse_time=datetime(2026, 7, 6, 9, 0),
        parse_version="v1",
    )

    repo.upsert_clean_article(article)
    repo.create_analyze_task("article-hash-1")
    repo.mark_clean_task_success("article-hash-1")
    repo.mark_clean_task_failed("article-hash-2", "parse failed")

    executed_sql = "\n".join(sql for sql, _ in engine.connection.executions)
    assert "INSERT INTO wechat_article_clean" in executed_sql
    assert "INSERT IGNORE INTO wechat_article_process_task" in executed_sql
    assert "task_type = 'clean_article'" in executed_sql
    assert "wechat_group_" not in executed_sql
    assert engine.connection.executions[0][1]["content_length"] == 88
    assert engine.connection.executions[1][1]["task_type"] == "analyze_article"
    assert engine.connection.executions[1][1]["ref_id"] == "article-hash-1"
