from __future__ import annotations

from datetime import datetime

import pytest

from app.storage.group_task_admin_repo import GroupFailedTaskRecord, MysqlGroupTaskAdminRepo


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
                        "id": 21,
                        "task_type": "analyze_group_msg",
                        "ref_type": "msg",
                        "ref_id": "hash-2",
                        "status": "failed",
                        "retry_count": 3,
                        "next_run_time": None,
                        "error_summary": "analysis timeout",
                        "update_time": datetime(2026, 7, 3, 13, 0, 0),
                    }
                ]
            )
        return FakeResult(rowcount=5)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_group_failed_task_record_keeps_error_summary_separate() -> None:
    record = GroupFailedTaskRecord(
        id=1,
        task_type="clean_group_msg",
        ref_type="msg",
        ref_id="hash-1",
        status="failed",
        retry_count=3,
        next_run_time=None,
        error_summary="clean timeout",
        update_time=datetime(2026, 7, 3, 12, 0, 0),
    )

    assert record.error_summary == "clean timeout"


def test_mysql_group_task_admin_repo_lists_failed_tasks_with_safe_fields_and_limit() -> None:
    engine = FakeEngine()
    repo = MysqlGroupTaskAdminRepo(engine)

    tasks = repo.list_failed_tasks(task_type="analyze_group_msg", limit=20)

    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert tasks[0].error_summary == "analysis timeout"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_group_process_task" in sql
    assert "status = 'failed'" in sql
    assert "task_type = :task_type" in sql
    assert "LEFT(error_msg, 200) AS error_summary" in sql
    assert "LIMIT :limit" in sql
    assert params["task_type"] == "analyze_group_msg"
    assert params["limit"] == 20
    _assert_failed_task_sql_is_isolated(sql)


def test_mysql_group_task_admin_repo_retries_failed_tasks_with_limit() -> None:
    engine = FakeEngine()
    repo = MysqlGroupTaskAdminRepo(engine)

    reset_count = repo.retry_failed_tasks(task_type="clean_group_msg", limit=5)

    assert reset_count == 5
    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_group_process_task" in sql
    assert "status = 'pending'" in sql
    assert "retry_count = 0" in sql
    assert "next_run_time = NULL" in sql
    assert "error_msg = NULL" in sql
    assert "WHERE status = 'failed'" in sql
    assert "task_type = :task_type" in sql
    assert "ORDER BY update_time ASC, id ASC" in sql
    assert "LIMIT :limit" in sql
    assert params["task_type"] == "clean_group_msg"
    assert params["limit"] == 5
    _assert_failed_task_sql_is_isolated(sql)


def test_mysql_group_task_admin_repo_rejects_non_positive_retry_limit() -> None:
    repo = MysqlGroupTaskAdminRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.retry_failed_tasks(task_type=None, limit=0)


def _assert_failed_task_sql_is_isolated(sql: str) -> None:
    assert "wechat_article_process_task" not in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "wechat_group_msg_analysis" not in sql
    assert "wechat_group_daily_report" not in sql
    assert "msg_content" not in sql
    assert "raw_content" not in sql
    assert "clean_content" not in sql
    assert "markdown_body" not in sql
