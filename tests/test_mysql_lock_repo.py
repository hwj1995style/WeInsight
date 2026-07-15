from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.storage.lock_repo import MysqlUiLockRepo


class FakeResult:
    def __init__(self, rowcount: int, scalar=None) -> None:
        self.rowcount = rowcount
        self.scalar = scalar

    def scalar_one_or_none(self):
        return self.scalar


class FakeConnection:
    def __init__(self, rowcount: int = 1, scalar=None) -> None:
        self.rowcount = rowcount
        self.scalar = scalar
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return FakeResult(self.rowcount, self.scalar)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rowcount: int = 1, scalar=None) -> None:
        self.connection = FakeConnection(rowcount, scalar)

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


def test_mysql_ui_lock_current_owner_is_read_only_and_bound() -> None:
    engine = FakeEngine(scalar="group")

    owner = MysqlUiLockRepo(engine).current_owner("wechat_ui")

    assert owner == "group"
    sql, params = engine.connection.executions[0]
    assert "SELECT owner_pipeline" in sql
    assert "WHERE lock_name = :lock_name" in sql
    assert params == {"lock_name": "wechat_ui"}


def test_mysql_ui_lock_current_owner_filters_expired_lease_by_now() -> None:
    engine = FakeEngine(scalar="group")
    now = datetime(2026, 7, 10, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    owner = MysqlUiLockRepo(engine).current_owner("wechat_ui", now)

    assert owner == "group"
    sql, params = engine.connection.executions[0]
    assert "expire_time > :now" in sql
    assert params == {
        "lock_name": "wechat_ui",
        "now": datetime(2026, 7, 10, 9, 30),
    }
