from __future__ import annotations

from datetime import datetime

from app.storage.group_repo import GroupRuntimeStatus, MysqlGroupStatusRepo


class FakeResult:
    def __init__(self, rows=None, first_row=None) -> None:
        self._rows = rows or []
        self._first_row = first_row

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first_row


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FROM wechat_group_config" in sql:
            return FakeResult(
                first_row={
                    "group_name": "核心群A",
                    "enabled": 1,
                    "is_core_group": 1,
                    "priority": 1,
                    "poll_interval_seconds": 30,
                    "last_collect_batch_id": "batch-1",
                    "last_success_collect_time": datetime(2026, 7, 3, 9, 0, 0),
                    "consecutive_fail_count": 0,
                    "error_msg": None,
                }
            )
        if "FROM wechat_group_collect_log" in sql:
            return FakeResult(
                first_row={
                    "status": "success",
                    "read_count": 3,
                    "insert_count": 2,
                    "duplicate_count": 1,
                    "error_code": None,
                    "screenshot_path": None,
                }
            )
        if "FROM wechat_ui_lock" in sql:
            return FakeResult(first_row={"owner_pipeline": None, "owner_task_id": None})
        raise AssertionError(f"unexpected sql: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_group_status_repo_reads_runtime_status_without_message_content() -> None:
    engine = FakeEngine()
    repo = MysqlGroupStatusRepo(engine)

    status = repo.get_group_status("核心群A")

    assert status == GroupRuntimeStatus(
        group_name="核心群A",
        enabled=True,
        is_core_group=True,
        priority=1,
        poll_interval_seconds=30,
        last_collect_batch_id="batch-1",
        last_success_collect_time=datetime(2026, 7, 3, 9, 0, 0),
        consecutive_fail_count=0,
        cursor_error_msg=None,
        latest_log_status="success",
        latest_log_read_count=3,
        latest_log_insert_count=2,
        latest_log_duplicate_count=1,
        latest_log_error_code=None,
        latest_log_screenshot_path=None,
        ui_lock_owner_pipeline=None,
        ui_lock_owner_task_id=None,
    )
    joined_sql = "\n".join(sql for sql, _ in engine.connection.executions)
    assert "msg_content" not in joined_sql
    assert "raw_content" not in joined_sql
