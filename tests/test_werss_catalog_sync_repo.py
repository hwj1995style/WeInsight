from datetime import datetime

import pytest

from app.integrations.werss_catalog import WeRSSCatalogItem
from app.storage.werss_catalog_sync_repo import (
    CatalogRow,
    WeRSSCatalogSyncBusyError,
    MysqlWeRSSCatalogSyncRepo,
    plan_catalog_sync,
)


NOW = datetime(2026, 7, 13, 16, 0)


def row(id, name, feed=None, source_id=None, status="unknown", missing_at=None):
    return CatalogRow(id, name, feed, source_id, status, None, missing_at)


def test_plan_binds_in_strict_id_feed_then_exact_name_order():
    rows = (
        row(1, "旧名", "http://old", "MP1", "active"),
        row(2, "乙", "http://127.0.0.1:8001/feed/MP2.atom"),
        row(3, "丙"),
    )
    items = (
        WeRSSCatalogItem("MP1", "甲", True),
        WeRSSCatalogItem("MP2", "乙新名", True),
        WeRSSCatalogItem("MP3", "丙", True),
    )

    plan = plan_catalog_sync(rows, items, (), NOW)

    assert [change.row_id for change in plan.changes] == [1, 2, 3]
    assert [change.source_id for change in plan.changes] == ["MP1", "MP2", "MP3"]
    assert plan.summary.created == 0


def test_plan_uses_percent_encoded_fixed_feed_url_and_never_fuzzy_name():
    rows = (row(1, "甲日报"),)
    items = (WeRSSCatalogItem("MP /甲", "甲", True),)

    plan = plan_catalog_sync(rows, items, (), NOW)

    assert plan.summary.created == 1
    assert plan.inserts[0].feed_url == "http://127.0.0.1:8001/feed/MP%20%2F%E7%94%B2.atom"


def test_plan_reports_conflict_instead_of_rebinding_exact_name():
    rows = (row(1, "甲", source_id="OTHER", status="active"),)

    plan = plan_catalog_sync(rows, (WeRSSCatalogItem("MP1", "甲", True),), (), NOW)

    assert plan.summary.conflicts == 1
    assert not plan.inserts
    assert all(change.source_id != "MP1" for change in plan.changes)


def test_plan_handles_disabled_missing_restore_and_historical_exclusion():
    rows = (
        row(1, "停用", source_id="MP1", status="active"),
        row(2, "缺失", source_id="MP2", status="active"),
        row(3, "恢复", source_id="MP3", status="missing", missing_at=NOW),
        row(4, "一箱蛋", source_id="MP4", status="active"),
    )
    items = (
        WeRSSCatalogItem("MP1", "停用", False),
        WeRSSCatalogItem("MP3", "恢复", True),
    )

    plan = plan_catalog_sync(rows, items, (), NOW)
    status_by_id = {change.row_id: change.status for change in plan.changes}

    assert status_by_id == {1: "disabled", 2: "missing", 3: "active", 4: "excluded"}
    assert (plan.summary.disabled, plan.summary.missing, plan.summary.restored, plan.summary.excluded) == (1, 1, 1, 1)


class Result:
    def __init__(self, rows=(), scalar=None): self.rows, self._scalar = rows, scalar
    def scalar_one(self): return self._scalar
    def mappings(self): return self
    def all(self): return list(self.rows)


class Connection:
    def __init__(self, lock=1, fail_on_insert=False):
        self.lock, self.fail_on_insert, self.executions = lock, fail_on_insert, []
    def execute(self, statement, params=None):
        sql = str(statement); self.executions.append((sql, params))
        if "GET_LOCK" in sql: return Result(scalar=self.lock)
        if "RELEASE_LOCK" in sql: return Result(scalar=1)
        if "SELECT" in sql and "FOR UPDATE" in sql: return Result([])
        if self.fail_on_insert and "INSERT INTO" in sql: raise RuntimeError("boom")
        return Result()


class Transaction:
    def __init__(self): self.committed = self.rolled_back = False
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True


class EngineConnection:
    def __init__(self, connection): self.connection, self.transaction, self.events = connection, Transaction(), []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def begin(self): self.events.append("begin"); return self.transaction
    def execute(self, *args, **kwargs): self.events.append("execute"); return self.connection.execute(*args, **kwargs)


class Engine:
    def __init__(self, connection): self.wrapper = EngineConnection(connection)
    def connect(self): return self.wrapper


def test_repo_uses_named_lock_row_lock_one_transaction_and_releases():
    connection = Connection()
    repo = MysqlWeRSSCatalogSyncRepo(Engine(connection))

    repo.sync_catalog((WeRSSCatalogItem("MP1", "甲", True),), (), NOW)

    sql = [item[0] for item in connection.executions]
    assert "GET_LOCK('weinsight:werss-catalog-sync', 0)" in sql[0]
    assert repo.engine.wrapper.events[:2] == ["begin", "execute"]
    assert "FOR UPDATE" in sql[1]
    assert "INSERT INTO wechat_public_account_config" in sql[2]
    assert "RELEASE_LOCK('weinsight:werss-catalog-sync')" in sql[-1]
    assert repo.engine.wrapper.transaction.committed


def test_repo_busy_rolls_back_transaction_and_still_releases_lock():
    connection = Connection(lock=0)
    repo = MysqlWeRSSCatalogSyncRepo(Engine(connection))

    with pytest.raises(WeRSSCatalogSyncBusyError, match="^werss_catalog_sync_busy$"):
        repo.sync_catalog((), (), NOW)

    assert repo.engine.wrapper.transaction.rolled_back
    assert any("RELEASE_LOCK" in sql for sql, _ in connection.executions)


def test_repo_rolls_back_entire_batch_and_releases_lock_on_failure():
    connection = Connection(fail_on_insert=True)
    repo = MysqlWeRSSCatalogSyncRepo(Engine(connection))

    with pytest.raises(RuntimeError, match="boom"):
        repo.sync_catalog((WeRSSCatalogItem("MP1", "甲", True),), (), NOW)

    assert repo.engine.wrapper.transaction.rolled_back
    assert not repo.engine.wrapper.transaction.committed
    assert "RELEASE_LOCK" in connection.executions[-1][0]


def test_new_source_insert_uses_compatibility_defaults_and_no_delete():
    connection = Connection()
    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "甲", True),), (), NOW
    )
    insert_sql, params = next(x for x in connection.executions if "INSERT INTO" in x[0])
    assert (params["enabled"], params["priority"], params["poll_interval_minutes"]) == (1, 10, 10)
    assert (params["request_timeout_seconds"], params["daily_window_start"], params["daily_window_end"]) == (30, "00:00:00", "23:59:59")
    assert params["collect_today_only"] == 1
    assert all("DELETE" not in sql.upper() for sql, _ in connection.executions)
