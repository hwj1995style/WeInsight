from __future__ import annotations

from datetime import datetime


class FakeResult:
    rowcount = 1

    def __init__(self, rows=None) -> None:
        self._rows = rows or []

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
        if "FOR SHARE" in sql:
            return FakeResult(
                [{"id": 9, "source_name": "行业观察", "enabled": 1}]
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


def test_mysql_article_collect_log_repo_inserts_article_log_without_group_tables() -> None:
    from app.storage.article_log_repo import ArticleCollectLogRecord, MysqlArticleCollectLogRepo

    engine = FakeEngine()
    repo = MysqlArticleCollectLogRepo(engine)

    repo.insert_collect_log(
        ArticleCollectLogRecord(
            batch_id="article-batch-1",
            account_name="行业观察",
            start_time=datetime(2026, 7, 6, 9, 0),
            end_time=datetime(2026, 7, 6, 9, 1),
            link_count=2,
            insert_count=1,
            status="success",
            stage="save_links",
        )
    )

    sql, params = engine.connection.executions[1]
    assert "INSERT INTO wechat_article_collect_log" in sql
    assert "wechat_group_" not in sql
    assert params["batch_id"] == "article-batch-1"
    assert params["account_name"] == "行业观察"
    assert params["link_count"] == 2
    assert params["insert_count"] == 1
    assert params["status"] == "success"
    assert params["stage"] == "save_links"


def test_rss_metrics_are_written_as_structured_columns() -> None:
    from app.storage.article_log_repo import ArticleCollectLogRecord, MysqlArticleCollectLogRepo
    engine = FakeEngine()
    MysqlArticleCollectLogRepo(engine).insert_collect_log(ArticleCollectLogRecord(
        batch_id="b", account_name="a", start_time=datetime(2026, 7, 11), end_time=None,
        status="success", feed_item_count=4, duplicate_count=2, invalid_count=1,
        http_status=304, elapsed_ms=9))
    sql, params = engine.connection.executions[1]
    for name in ("feed_item_count", "duplicate_count", "invalid_count", "http_status", "elapsed_ms"):
        assert name in sql and params[name] is not None
