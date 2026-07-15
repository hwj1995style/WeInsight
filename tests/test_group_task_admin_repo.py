from __future__ import annotations

from datetime import date, datetime

import pytest

from app.storage.group_task_admin_repo import MysqlGroupTaskAdminRepo


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
        if "FROM wechat_group_process_task" in sql:
            return FakeResult(
                rows=[
                    {
                        "id": 11,
                        "task_type": "analyze_group_msg",
                        "ref_type": "msg",
                        "ref_id": "hash-1",
                        "status": "failed",
                        "retry_count": 3,
                        "next_run_time": None,
                        "error_msg": "analysis timeout",
                        "update_time": datetime(2026, 7, 3, 12, 0, 0),
                    }
                ]
            )
        return FakeResult(rowcount=2)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_group_task_admin_repo_lists_group_tasks_without_message_tables() -> None:
    engine = FakeEngine()
    repo = MysqlGroupTaskAdminRepo(engine)

    tasks = repo.list_tasks(task_type="analyze_group_msg", status="failed", ref_id="hash-1", limit=10)

    assert len(tasks) == 1
    assert tasks[0].task_type == "analyze_group_msg"
    assert tasks[0].ref_id == "hash-1"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_group_process_task" in sql
    assert "task_type = :task_type" in sql
    assert "status = :status" in sql
    assert "ref_id = :ref_id" in sql
    assert params["task_type"] == "analyze_group_msg"
    assert params["status"] == "failed"
    assert params["ref_id"] == "hash-1"
    assert params["limit"] == 10
    _assert_group_task_admin_sql_is_isolated(sql)


def test_mysql_group_task_admin_repo_resets_msg_task_by_expected_ref_type() -> None:
    engine = FakeEngine()
    repo = MysqlGroupTaskAdminRepo(engine)

    reset_count = repo.reset_task(task_type="clean_group_msg", ref_id="hash-1")

    assert reset_count == 2
    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_group_process_task" in sql
    assert "status = 'pending'" in sql
    assert "retry_count = 0" in sql
    assert "next_run_time = NULL" in sql
    assert "error_msg = NULL" in sql
    assert "task_type = :task_type" in sql
    assert "ref_type = :ref_type" in sql
    assert params["task_type"] == "clean_group_msg"
    assert params["ref_type"] == "msg"
    assert params["ref_id"] == "hash-1"
    _assert_group_task_admin_sql_is_isolated(sql)


def test_mysql_group_task_admin_repo_upserts_daily_report_date_task() -> None:
    engine = FakeEngine()
    repo = MysqlGroupTaskAdminRepo(engine)

    reset_count = repo.reset_daily_report_date(date(2026, 7, 3))

    assert reset_count == 2
    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_group_process_task" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert params["task_type"] == "group_daily_report"
    assert params["ref_type"] == "date"
    assert params["ref_id"] == "2026-07-03"
    _assert_group_task_admin_sql_is_isolated(sql)


def test_mysql_group_task_admin_repo_rejects_article_task_type() -> None:
    repo = MysqlGroupTaskAdminRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.reset_task(task_type="clean_article", ref_id="article-hash")


def _assert_group_task_admin_sql_is_isolated(sql: str) -> None:
    assert "wechat_article_process_task" not in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "wechat_group_msg_analysis" not in sql
    assert "wechat_group_daily_report" not in sql
    assert "msg_content" not in sql
    assert "raw_content" not in sql
    assert "clean_content" not in sql
    assert "markdown_body" not in sql
