from __future__ import annotations

from datetime import datetime

from app.domain.group_cleaning import CleanGroupMessage
from app.storage.group_clean_repo import MysqlGroupCleanRepo


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
                        "msg_hash": "hash-1",
                        "group_name": "核心群A",
                        "sender_name": "张三",
                        "msg_time_display": "08:31",
                        "msg_type": "text",
                        "msg_content": "联系 13812345678",
                        "raw_content": "联系 13812345678",
                        "collect_time": datetime(2026, 7, 3, 9, 0, 0),
                        "collect_batch_id": "batch-1",
                    }
                ]
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


def test_mysql_group_clean_repo_lists_pending_clean_raw_messages() -> None:
    engine = FakeEngine()
    repo = MysqlGroupCleanRepo(engine)

    raws = repo.list_pending_clean_raw_messages(limit=5)

    assert len(raws) == 1
    assert raws[0].msg_hash == "hash-1"
    sql, params = engine.connection.executions[0]
    assert "wechat_group_process_task" in sql
    assert "task_type = 'clean_group_msg'" in sql
    assert "status = 'pending'" in sql
    assert params["limit"] == 5


def test_mysql_group_clean_repo_upserts_clean_message_without_raw_content() -> None:
    engine = FakeEngine()
    repo = MysqlGroupCleanRepo(engine)
    clean = CleanGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_hash="sender-hash",
        sender_display="张***",
        msg_time_display="08:31",
        msg_time_inferred=None,
        msg_type="text",
        clean_content="联系 138****5678",
        content_length=13,
        is_empty=False,
        has_phone=True,
        has_wechat_id=False,
        clean_version="v1",
        source_collect_batch_id="batch-1",
        clean_time=datetime(2026, 7, 3, 9, 1, 0),
    )

    repo.upsert_clean_message(clean)

    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_group_msg_clean" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "raw_content" not in sql
    assert "msg_content" not in sql
    assert params["clean_content"] == "联系 138****5678"


def test_mysql_group_clean_repo_creates_analyze_task_and_marks_success() -> None:
    engine = FakeEngine()
    repo = MysqlGroupCleanRepo(engine)

    repo.create_analyze_task("hash-1")
    repo.mark_clean_task_success("hash-1")

    insert_sql, insert_params = engine.connection.executions[0]
    update_sql, update_params = engine.connection.executions[1]
    assert "INSERT IGNORE INTO wechat_group_process_task" in insert_sql
    assert insert_params["task_type"] == "analyze_group_msg"
    assert "UPDATE wechat_group_process_task" in update_sql
    assert "status = 'success'" in update_sql
    assert update_params["ref_id"] == "hash-1"
