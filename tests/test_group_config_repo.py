from __future__ import annotations

from app.storage.group_repo import GroupConfigRecord, MysqlGroupConfigRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []
        self.rowcount = 1

    def mappings(self):
        return self

    def all(self):
        return self._rows


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


def test_mysql_group_config_repo_lists_group_configs() -> None:
    engine = FakeEngine(
        rows=[
            {
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
        )
    ]
    sql, _ = engine.connection.executions[0]
    assert "FROM wechat_group_config" in sql
    assert "ORDER BY priority ASC" in sql


def test_mysql_group_config_repo_disables_group_config() -> None:
    engine = FakeEngine()
    repo = MysqlGroupConfigRepo(engine)

    repo.disable_group("核心群A")

    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_group_config" in sql
    assert "enabled = 0" in sql
    assert params["group_name"] == "核心群A"
