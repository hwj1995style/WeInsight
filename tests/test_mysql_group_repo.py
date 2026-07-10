from __future__ import annotations

from datetime import datetime

from app.domain.group_messages import GroupCursor, RawGroupMessage
from app.storage.group_repo import MysqlGroupMessageRepo


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_repo_insert_raw_uses_insert_ignore() -> None:
    engine = FakeEngine()
    repo = MysqlGroupMessageRepo(engine)
    message = RawGroupMessage(
        msg_hash="h1",
        group_name="核心群A",
        sender_name="张三",
        msg_time_display="08:31",
        msg_type="text",
        msg_content="求购鸡蛋",
        raw_content="求购鸡蛋",
        collect_time=datetime(2026, 7, 2, 8, 33),
        collect_batch_id="batch-1",
    )

    inserted = repo.insert_raw_ignore_duplicates([message])

    assert inserted == 1
    sql, params = engine.connection.executions[0]
    assert "INSERT IGNORE INTO wechat_group_msg_raw" in sql
    assert params[0]["msg_hash"] == "h1"


def test_mysql_repo_insert_raw_creates_clean_tasks() -> None:
    engine = FakeEngine()
    repo = MysqlGroupMessageRepo(engine)
    message = RawGroupMessage(
        msg_hash="h1",
        group_name="核心群A",
        sender_name="张三",
        msg_time_display="08:31",
        msg_type="text",
        msg_content="求购鸡蛋",
        raw_content="求购鸡蛋",
        collect_time=datetime(2026, 7, 2, 8, 33),
        collect_batch_id="batch-1",
    )

    repo.insert_raw_ignore_duplicates([message])

    sql, params = engine.connection.executions[1]
    assert "INSERT IGNORE INTO wechat_group_process_task" in sql
    assert params[0]["task_type"] == "clean_group_msg"
    assert params[0]["ref_id"] == "h1"


def test_mysql_repo_update_cursor_uses_upsert() -> None:
    engine = FakeEngine()
    repo = MysqlGroupMessageRepo(engine)
    cursor = GroupCursor(
        group_name="核心群A",
        last_msg_hash="h1",
        last_msg_time_display="08:31",
        last_msg_content_preview="求购鸡蛋",
        last_sender_name="张三",
        last_success_collect_time=datetime(2026, 7, 2, 8, 33),
        last_collect_batch_id="batch-1",
    )

    repo.update_cursor(cursor)

    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_group_collect_cursor" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "consecutive_fail_count = 0" in sql
    assert "error_msg = NULL" in sql
    assert params["group_name"] == "核心群A"
