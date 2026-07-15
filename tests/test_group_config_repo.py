from __future__ import annotations

import re
from datetime import datetime

import pytest

from app.storage.group_repo import GroupConfigRecord, MysqlGroupConfigRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []
        self.rowcount = 1
        self.lastrowid = 7

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return FakeResult(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rows=None) -> None:
        self.connection = FakeConnection(rows)

    def begin(self):
        return self.connection


def test_mysql_group_config_repo_upserts_group_config() -> None:
    engine = FakeEngine()
    repo = MysqlGroupConfigRepo(engine)

    repo.upsert_group_config(
        group_name="核心群A",
        enabled=True,
        priority=1,
        poll_interval_seconds=30,
        backtrack_pages=1,
        extra_backtrack_pages=3,
        is_core_group=True,
        remark="授权测试群",
    )

    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_group_config" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert params["group_name"] == "核心群A"
    assert params["enabled"] == 1
    assert params["is_core_group"] == 1


def test_mysql_group_config_repo_creates_without_name_upsert() -> None:
    engine = FakeEngine()

    source_id = MysqlGroupConfigRepo(engine).create_group_config(
        group_name="核心群A",
        enabled=True,
        priority=1,
        poll_interval_seconds=30,
        backtrack_pages=1,
        extra_backtrack_pages=3,
        is_core_group=True,
        remark=None,
    )

    assert source_id == 7
    sql, _ = engine.connection.executions[0]
    assert "INSERT INTO wechat_group_config" in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql


def test_mysql_group_config_repo_lists_group_configs() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 7,
                "group_name": "核心群A",
                "enabled": 1,
                "priority": 1,
                "poll_interval_seconds": 30,
                "backtrack_pages": 1,
                "extra_backtrack_pages": 3,
                "is_core_group": 1,
                "remark": "授权测试群",
            }
        ]
    )
    repo = MysqlGroupConfigRepo(engine)

    groups = repo.list_groups()

    assert groups == [
        GroupConfigRecord(
            group_name="核心群A",
            priority=1,
            poll_interval_seconds=30,
            enabled=True,
            is_core_group=True,
            backtrack_pages=1,
            extra_backtrack_pages=3,
            remark="授权测试群",
            id=7,
        )
    ]
    sql, _ = engine.connection.executions[0]
    assert "FROM wechat_group_config" in sql
    assert "ORDER BY priority ASC" in sql
    assert re.search(r"SELECT\s+id\s*,", sql)


def test_mysql_group_config_repo_pages_with_limit_and_offset() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 7,
                "group_name": "核心群A",
                "enabled": 1,
                "priority": 1,
                "poll_interval_seconds": 30,
                "backtrack_pages": 1,
                "extra_backtrack_pages": 3,
                "is_core_group": 1,
                "remark": None,
            }
        ]
    )

    groups = MysqlGroupConfigRepo(engine).list_groups_page(limit=21, offset=40)

    assert groups[0].id == 7
    sql, params = engine.connection.executions[0]
    assert "LIMIT :limit" in sql
    assert "OFFSET :offset" in sql
    assert params == {"limit": 21, "offset": 40}


def test_mysql_group_config_repo_lists_enabled_job_choices_with_sql_limit() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 7,
                "group_name": "核心群A",
                "enabled": 1,
                "priority": 1,
                "poll_interval_seconds": 30,
                "backtrack_pages": 1,
                "extra_backtrack_pages": 3,
                "is_core_group": 1,
                "remark": None,
            }
        ]
    )

    groups = MysqlGroupConfigRepo(engine).list_enabled_groups_for_job(limit=100)

    assert groups[0].id == 7
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_group_config" in sql
    assert "WHERE enabled = 1" in sql
    assert "ORDER BY priority ASC, group_name ASC, id ASC" in sql
    assert "LIMIT :limit" in sql
    assert "OFFSET" not in sql
    assert params == {"limit": 100}


@pytest.mark.parametrize("limit", [0, 101, True, "10"])
def test_mysql_group_config_repo_rejects_invalid_job_choice_limit(limit) -> None:
    engine = FakeEngine()

    with pytest.raises(ValueError, match="limit"):
        MysqlGroupConfigRepo(engine).list_enabled_groups_for_job(limit=limit)

    assert engine.connection.executions == []


def test_mysql_group_config_repo_disables_group_config() -> None:
    engine = FakeEngine()
    repo = MysqlGroupConfigRepo(engine)

    repo.disable_group("核心群A")

    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_group_config" in sql
    assert "enabled = 0" in sql
    assert params["group_name"] == "核心群A"


def test_mysql_group_config_repo_gets_group_by_stable_id() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 7,
                "group_name": "核心群A",
                "enabled": 1,
                "priority": 1,
                "poll_interval_seconds": 30,
                "backtrack_pages": 1,
                "extra_backtrack_pages": 3,
                "is_core_group": 1,
                "remark": None,
            }
        ]
    )

    record = MysqlGroupConfigRepo(engine).get_group(7)

    assert record is not None and record.id == 7
    sql, params = engine.connection.executions[0]
    assert re.search(r"SELECT\s+id\s*,", sql)
    assert "WHERE id = :source_id" in sql
    assert params == {"source_id": 7}


def test_mysql_group_config_repo_updates_group_by_stable_id() -> None:
    engine = FakeEngine()
    repo = MysqlGroupConfigRepo(engine)

    affected = repo.update_group_config(
        7,
        group_name="新群名",
        priority=2,
        poll_interval_seconds=45,
        backtrack_pages=2,
        extra_backtrack_pages=4,
        is_core_group=False,
        remark="更新",
    )

    assert affected == 1
    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_group_config" in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql
    assert "WHERE id = :source_id" in sql
    assert params["source_id"] == 7
    assert params["group_name"] == "新群名"
    assert params["is_core_group"] == 0


def test_mysql_group_config_repo_sets_enabled_and_deletes_disabled_by_id() -> None:
    engine = FakeEngine()
    repo = MysqlGroupConfigRepo(engine)

    assert repo.set_group_enabled(7, False) == 1
    assert repo.delete_group(7) == 1

    enable_sql, enable_params = engine.connection.executions[0]
    delete_sql, delete_params = engine.connection.executions[1]
    assert "WHERE id = :source_id" in enable_sql
    assert enable_params == {"source_id": 7, "enabled": 0}
    assert "DELETE FROM wechat_group_config" in delete_sql
    assert "WHERE id = :source_id" in delete_sql
    assert "enabled = 0" in delete_sql
    assert delete_params == {"source_id": 7}


def test_mysql_group_config_repo_due_query_selects_qualified_id() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 7,
                "group_name": "核心群A",
                "priority": 1,
                "poll_interval_seconds": 30,
            }
        ]
    )

    groups = MysqlGroupConfigRepo(engine).list_due_groups(
        datetime(2026, 7, 10, 9, 0), 1
    )

    assert groups[0].id == 7
    sql, _ = engine.connection.executions[0]
    assert re.search(r"SELECT\s+cfg\.id\s*,", sql)
