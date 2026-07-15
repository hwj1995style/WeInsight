from __future__ import annotations

from datetime import datetime

from app.storage.group_repo import GroupCollectLogRecord, MysqlGroupCollectLogRepo


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
                [{"id": 7, "source_name": "核心群A", "enabled": 1}]
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


def test_mysql_group_collect_log_repo_inserts_success_log() -> None:
    engine = FakeEngine()
    repo = MysqlGroupCollectLogRepo(engine)
    record = GroupCollectLogRecord(
        batch_id="batch-1",
        source_name="核心群A",
        start_time=datetime(2026, 7, 3, 9, 0, 0),
        end_time=datetime(2026, 7, 3, 9, 0, 5),
        read_count=2,
        insert_count=1,
        duplicate_count=1,
        status="success",
    )

    repo.insert_collect_log(record)

    sql, params = engine.connection.executions[1]
    assert "INSERT INTO wechat_group_collect_log" in sql
    assert params["batch_id"] == "batch-1"
    assert params["source_name"] == "核心群A"
    assert params["status"] == "success"


def test_mysql_group_collect_log_repo_marks_group_collect_failed() -> None:
    engine = FakeEngine()
    repo = MysqlGroupCollectLogRepo(engine)

    repo.mark_group_collect_failed("核心群A", "boom")

    sql, params = engine.connection.executions[1]
    assert "INSERT INTO wechat_group_collect_cursor" in sql
    assert "consecutive_fail_count = consecutive_fail_count + 1" in sql
    assert params["group_name"] == "核心群A"
    assert params["error_msg"] == "boom"
