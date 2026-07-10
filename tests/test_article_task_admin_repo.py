from __future__ import annotations

from datetime import datetime

import pytest

from app.storage.article_task_admin_repo import MysqlArticleTaskAdminRepo


class FakeResult:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FROM wechat_article_process_task" in sql:
            return FakeResult(
                rows=[
                    {
                        "id": 31,
                        "task_type": "clean_article",
                        "ref_type": "article",
                        "ref_id": "article-hash-1",
                        "status": "failed",
                        "retry_count": 3,
                        "next_run_time": None,
                        "error_summary": "parse failed https://mp.weixin.qq.com/s/abc",
                        "update_time": datetime(2026, 7, 6, 13, 0, 0),
                    }
                ]
            )
        return FakeResult(rowcount=4)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_article_task_admin_queries_only_article_task_table() -> None:
    engine = FakeEngine()
    repo = MysqlArticleTaskAdminRepo(engine)

    tasks = repo.list_failed_tasks(task_type="clean_article", limit=10)

    assert len(tasks) == 1
    assert tasks[0].id == 31
    assert tasks[0].task_type == "clean_article"
    assert tasks[0].ref_type == "article"
    assert tasks[0].ref_id == "article-hash-1"
    assert tasks[0].status == "failed"
    assert tasks[0].retry_count == 3
    assert tasks[0].error_summary == "parse failed [redacted-url]"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_process_task" in sql
    assert "task_type = :task_type" in sql
    assert params["task_type"] == "clean_article"
    assert params["limit"] == 10
    _assert_article_task_admin_sql_is_isolated(sql)


def test_article_task_admin_retries_failed_tasks_without_group_tables() -> None:
    engine = FakeEngine()
    repo = MysqlArticleTaskAdminRepo(engine)

    reset_count = repo.retry_failed_tasks(task_type="analyze_article", limit=4)

    assert reset_count == 4
    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_article_process_task" in sql
    assert "status = 'pending'" in sql
    assert "retry_count = 0" in sql
    assert "error_msg = NULL" in sql
    assert params["task_type"] == "analyze_article"
    assert params["limit"] == 4
    _assert_article_task_admin_sql_is_isolated(sql)


def test_article_task_admin_rejects_group_task_type() -> None:
    repo = MysqlArticleTaskAdminRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.list_failed_tasks(task_type="clean_group_msg", limit=10)


def test_article_task_admin_rejects_non_positive_limit() -> None:
    repo = MysqlArticleTaskAdminRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.retry_failed_tasks(task_type=None, limit=0)


def _assert_article_task_admin_sql_is_isolated(sql: str) -> None:
    assert "wechat_group_process_task" not in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "wechat_group_daily_report" not in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "article_url" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
