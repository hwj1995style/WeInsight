from __future__ import annotations

from datetime import datetime

from app.storage.lock_repo import MysqlUiLockRepo


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return FakeResult(self.rowcount)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rowcount: int = 1) -> None:
        self.connection = FakeConnection(rowcount)

    def begin(self):
        return self.connection


def test_mysql_ui_lock_acquire_uses_insert_ignore() -> None:
    engine = FakeEngine(rowcount=1)
    repo = MysqlUiLockRepo(engine)

    acquired = repo.acquire(
        lock_name="wechat_ui",
        owner_pipeline="group",
        owner_task_id="batch-1",
        now=datetime(2026, 7, 3, 9, 0, 0),
        lease_seconds=120,
    )

    assert acquired is True
    delete_sql, delete_params = engine.connection.executions[0]
    insert_sql, insert_params = engine.connection.executions[1]
    assert "DELETE FROM wechat_ui_lock" in delete_sql
    assert "expire_time <= :now" in delete_sql
    assert delete_params["lock_name"] == "wechat_ui"
    assert "INSERT IGNORE INTO wechat_ui_lock" in insert_sql
    assert insert_params["owner_pipeline"] == "group"
    assert insert_params["owner_task_id"] == "batch-1"


def test_mysql_ui_lock_release_deletes_only_matching_owner() -> None:
    engine = FakeEngine(rowcount=1)
    repo = MysqlUiLockRepo(engine)

    released = repo.release("wechat_ui", "group", "batch-1")

    assert released is True
    sql, params = engine.connection.executions[0]
    assert "DELETE FROM wechat_ui_lock" in sql
    assert "owner_pipeline = :owner_pipeline" in sql
    assert "owner_task_id = :owner_task_id" in sql
    assert params["owner_task_id"] == "batch-1"
