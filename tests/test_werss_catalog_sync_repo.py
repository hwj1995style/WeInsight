from datetime import datetime
import json

import pytest
from sqlalchemy import create_engine, text

from app.integrations.werss_catalog import WeRSSCatalogItem
from app.storage.werss_catalog_sync_repo import (
    CatalogRow,
    WeRSSCatalogSyncBusyError,
    MysqlWeRSSCatalogSyncRepo,
    plan_catalog_sync,
    prepare_safe_catalog_changes,
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


@pytest.mark.parametrize(
    ("existing", "source_id"),
    [
        (row(1, "旧排除名", "http://old", "MPX", "active"), "MPX"),
        (row(1, "旧排除名", "http://127.0.0.1:8001/feed/MPX.atom", None, "active"), "MPX"),
        (row(1, " 一箱蛋 ", None, None, "active"), "MPX"),
    ],
)
def test_excluded_item_binds_by_id_feed_or_normalized_exact_name(existing, source_id):
    item = WeRSSCatalogItem(source_id, " 一箱蛋 ", True)

    plan = plan_catalog_sync((existing,), (), (item,), NOW)

    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert (change.row_id, change.source_id, change.feed_url, change.status) == (
        1,
        source_id,
        f"http://127.0.0.1:8001/feed/{source_id}.atom",
        "excluded",
    )


def test_unmatched_historical_exclusion_preserves_null_identity_and_feed():
    historical = row(1, " 一箱蛋 ", None, None, "active")

    plan = plan_catalog_sync((historical,), (), (), NOW)

    change = plan.changes[0]
    assert change.status == "excluded"
    assert change.source_id is None
    assert change.feed_url is None


class Result:
    def __init__(self, rows=(), scalar=None): self.rows, self._scalar = rows, scalar
    def scalar_one(self): return self._scalar
    def mappings(self): return self
    def all(self): return list(self.rows)
    def first(self): return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, lock=1, fail_on_insert=False, fail_on_release=False, rows=()):
        self.lock, self.fail_on_insert = lock, fail_on_insert
        self.fail_on_release = fail_on_release
        self.rows = [dict(item) for item in rows]
        self.executions = []
        self.audit_metrics = None
        self.invalidated = False
    def invalidate(self): self.invalidated = True
    def execute(self, statement, params=None):
        sql = str(statement); self.executions.append((sql, params))
        if "GET_LOCK" in sql: return Result(scalar=self.lock)
        if "RELEASE_LOCK" in sql:
            if self.fail_on_release: raise RuntimeError("release failed")
            return Result(scalar=1)
        if "FROM wechat_public_account_config" in sql and "FOR UPDATE" in sql: return Result(self.rows)
        if "FROM wechat_collection_job_event" in sql:
            return Result(() if self.audit_metrics is None else ({"metrics_json": self.audit_metrics},))
        if self.fail_on_insert and "INSERT INTO" in sql: raise RuntimeError("boom")
        if "INSERT INTO wechat_collection_job_event" in sql:
            self.audit_metrics = params["metrics_json"]
        elif "UPDATE wechat_public_account_config" in sql:
            target = next(item for item in self.rows if item["id"] == params["id"])
            target.update({
                "account_name": params["account_name"],
                "feed_url": params["feed_url"],
                "werss_source_id": params["werss_source_id"],
                "upstream_status": params["upstream_status"],
                "upstream_last_seen_at": params["upstream_last_seen_at"],
                "upstream_missing_at": params["upstream_missing_at"],
            })
        elif "INSERT INTO wechat_public_account_config" in sql:
            self.rows.append({
                "id": max((item["id"] for item in self.rows), default=0) + 1,
                "account_name": params["account_name"],
                "feed_url": params["feed_url"],
                "werss_source_id": params["werss_source_id"],
                "upstream_status": params["upstream_status"],
                "upstream_last_seen_at": params["upstream_last_seen_at"],
                "upstream_missing_at": None,
            })
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
    def invalidate(self): self.connection.invalidate()


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


def test_repo_renames_history_only_when_old_name_identifies_one_config():
    connection = Connection(rows=({
        "id": 1, "account_name": "旧名", "feed_url": "http://old",
        "werss_source_id": "MP1", "upstream_status": "active",
        "upstream_last_seen_at": NOW, "upstream_missing_at": None,
    },))

    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "新名", True),), (), NOW
    )

    history_updates = [
        (sql, params) for sql, params in connection.executions
        if "UPDATE wechat_article_raw" in sql or "UPDATE wechat_article_collect_log" in sql
    ]
    assert len(history_updates) == 2
    assert all(params == {"old_name": "旧名", "new_name": "新名"} for _, params in history_updates)


def test_repo_does_not_migrate_ambiguous_same_name_history():
    common = {
        "account_name": "同名", "upstream_status": "active",
        "upstream_last_seen_at": NOW, "upstream_missing_at": None,
    }
    connection = Connection(rows=(
        {"id": 1, "feed_url": "http://one", "werss_source_id": "MP1", **common},
        {"id": 2, "feed_url": "http://two", "werss_source_id": "MP2", **common},
    ))

    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "新名", True), WeRSSCatalogItem("MP2", "同名", True)), (), NOW
    )

    assert all("UPDATE wechat_article_raw" not in sql for sql, _ in connection.executions)


def test_repo_migrates_history_after_other_source_releases_target_name():
    connection = Connection(rows=(
        {
            "id": 1, "account_name": "旧名", "feed_url": "http://one",
            "werss_source_id": "MP1", "upstream_status": "active",
            "upstream_last_seen_at": NOW, "upstream_missing_at": None,
        },
        {
            "id": 2, "account_name": "新名", "feed_url": "http://two",
            "werss_source_id": "MP2", "upstream_status": "active",
            "upstream_last_seen_at": NOW, "upstream_missing_at": None,
        },
    ))

    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "新名", True), WeRSSCatalogItem("MP2", "另名", True)), (), NOW
    )

    risky_migrations = [
        params for sql, params in connection.executions
        if "UPDATE wechat_article_raw" in sql and params["old_name"] == "旧名"
    ]
    assert risky_migrations == [{"old_name": "旧名", "new_name": "新名"}]


def _sqlite_unique_catalog(rows):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE wechat_public_account_config (
                id INTEGER PRIMARY KEY,
                account_name VARCHAR(200) NOT NULL UNIQUE,
                feed_url VARCHAR(500), werss_source_id VARCHAR(200),
                upstream_status VARCHAR(20), upstream_last_seen_at DATETIME,
                upstream_missing_at DATETIME, update_time DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE wechat_article_raw (account_name VARCHAR(200))
        """))
        connection.execute(text("""
            CREATE TABLE wechat_article_collect_log (account_name VARCHAR(200))
        """))
        connection.execute(text("""
            INSERT INTO wechat_public_account_config
              (id, account_name, feed_url, werss_source_id, upstream_status)
            VALUES (:id, :account_name, :feed_url, :werss_source_id, :upstream_status)
        """), [{
            "id": item.id, "account_name": item.account_name,
            "feed_url": item.feed_url, "werss_source_id": item.werss_source_id,
            "upstream_status": item.upstream_status,
        } for item in rows])
    return engine


def _execute_safe_changes(engine, rows, changes):
    ordered = prepare_safe_catalog_changes(rows, changes)
    rows_by_id = {row.id: row for row in rows}
    name_counts = {row.account_name: sum(x.account_name == row.account_name for x in rows) for row in rows}
    with engine.begin() as connection:
        for change in ordered:
            original = rows_by_id[change.row_id]
            MysqlWeRSSCatalogSyncRepo._apply_change(
                connection, change, original=original,
                original_name_is_unique=name_counts[original.account_name] == 1,
                new_name_is_safe=True,
            )
        return connection.execute(text(
            "SELECT id, account_name, upstream_status FROM wechat_public_account_config ORDER BY id"
        )).all()


@pytest.mark.filterwarnings("ignore:The default datetime adapter is deprecated:DeprecationWarning")
def test_static_name_owner_keeps_target_name_while_other_state_updates_under_unique_constraint():
    rows = (
        row(1, "A", source_id="MP1", status="active"),
        row(2, "B", source_id="MP2", status="active"),
    )
    plan = plan_catalog_sync(
        rows,
        (WeRSSCatalogItem("MP1", "B", False), WeRSSCatalogItem("MP2", "B", True)),
        (), NOW,
    )

    result = _execute_safe_changes(_sqlite_unique_catalog(rows), rows, plan.changes)

    assert result == [(1, "A", "disabled"), (2, "B", "active")]


@pytest.mark.filterwarnings("ignore:The default datetime adapter is deprecated:DeprecationWarning")
def test_chain_rename_releases_unique_target_before_claiming_it():
    rows = (
        row(1, "A", source_id="MP1", status="active"),
        row(2, "B", source_id="MP2", status="active"),
    )
    plan = plan_catalog_sync(
        rows,
        (WeRSSCatalogItem("MP1", "B", True), WeRSSCatalogItem("MP2", "C", True)),
        (), NOW,
    )

    result = _execute_safe_changes(_sqlite_unique_catalog(rows), rows, plan.changes)

    assert result == [(1, "B", "active"), (2, "C", "active")]


@pytest.mark.filterwarnings("ignore:The default datetime adapter is deprecated:DeprecationWarning")
def test_rename_cycle_keeps_original_names_without_rolling_back_state_updates():
    rows = (
        row(1, "A", source_id="MP1", status="active"),
        row(2, "B", source_id="MP2", status="active"),
    )
    plan = plan_catalog_sync(
        rows,
        (WeRSSCatalogItem("MP1", "B", False), WeRSSCatalogItem("MP2", "A", False)),
        (), NOW,
    )

    result = _execute_safe_changes(_sqlite_unique_catalog(rows), rows, plan.changes)

    assert result == [(1, "A", "disabled"), (2, "B", "disabled")]


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


def test_repo_writes_safe_structured_summary_audit_in_same_transaction():
    connection = Connection()

    summary = MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "甲", True),), (), NOW
    )

    audit_sql, params = next(x for x in connection.executions if "INSERT INTO wechat_collection_job_event" in x[0])
    assert "metrics_json" in audit_sql
    assert params["event_type"] == "werss_catalog_sync_changed"
    assert params["message"] == "WeRSS catalog synchronization changed source configuration."
    assert params["actor_name"] == "werss-catalog-sync"
    metrics = json.loads(params["metrics_json"])
    digest = metrics.pop("catalog_digest")
    assert len(digest) == 64
    assert metrics == {"conflicts": 0, "created": 1, "disabled": 0, "excluded": 0, "missing": 0, "restored": 0, "updated": 0}
    assert summary.created == 1


def test_repo_does_not_write_audit_for_idempotent_no_change_catalog():
    connection = Connection(rows=({
        "id": 1,
        "account_name": "甲",
        "feed_url": "http://127.0.0.1:8001/feed/MP1.atom",
        "werss_source_id": "MP1",
        "upstream_status": "active",
        "upstream_last_seen_at": NOW,
        "upstream_missing_at": None,
    },))

    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "甲", True),), (), NOW
    )

    assert all("wechat_collection_job_event" not in sql for sql, _ in connection.executions)


def test_repo_audits_conflict_even_without_source_write():
    connection = Connection(rows=({
        "id": 1, "account_name": "甲", "feed_url": None,
        "werss_source_id": "OTHER", "upstream_status": "missing",
        "upstream_last_seen_at": NOW, "upstream_missing_at": NOW,
    },))

    MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
        (WeRSSCatalogItem("MP1", "甲", True), WeRSSCatalogItem("OTHER", "甲旧", True)), (), NOW
    )

    params = next(params for sql, params in connection.executions if "INSERT INTO wechat_collection_job_event" in sql)
    assert '"conflicts":1' in params["metrics_json"]


def test_repo_deduplicates_identical_conflict_audit():
    connection = Connection(rows=({
        "id": 1, "account_name": "甲", "feed_url": None,
        "werss_source_id": "OTHER", "upstream_status": "missing",
        "upstream_last_seen_at": NOW, "upstream_missing_at": NOW,
    },))
    repo = MysqlWeRSSCatalogSyncRepo(Engine(connection))
    items = (WeRSSCatalogItem("MP1", "甲", True), WeRSSCatalogItem("OTHER", "甲", True))

    repo.sync_catalog(items, (), NOW)
    repo.sync_catalog(items, (), NOW)

    audit_inserts = [sql for sql, _ in connection.executions if "INSERT INTO wechat_collection_job_event" in sql]
    assert len(audit_inserts) == 1


def test_repo_deduplicates_conflict_audit_after_first_round_restores_and_renames():
    connection = Connection(rows=(
        {
            "id": 1, "account_name": "旧名", "feed_url": "http://old",
            "werss_source_id": "MP1", "upstream_status": "missing",
            "upstream_last_seen_at": NOW, "upstream_missing_at": NOW,
        },
        {
            "id": 2, "account_name": "冲突名", "feed_url": "http://other",
            "werss_source_id": "OTHER", "upstream_status": "active",
            "upstream_last_seen_at": NOW, "upstream_missing_at": None,
        },
    ))
    repo = MysqlWeRSSCatalogSyncRepo(Engine(connection))
    items = (
        WeRSSCatalogItem("MPX", "冲突名", True),
        WeRSSCatalogItem("MP1", "新名", True),
        WeRSSCatalogItem("OTHER", "冲突名", True),
    )

    summaries = [repo.sync_catalog(items, (), NOW) for _ in range(3)]

    assert (summaries[0].restored, summaries[0].conflicts) == (1, 1)
    assert [(item.restored, item.updated, item.conflicts) for item in summaries[1:]] == [
        (0, 0, 1), (0, 0, 1)
    ]
    audit_inserts = [sql for sql, _ in connection.executions if "INSERT INTO wechat_collection_job_event" in sql]
    assert len(audit_inserts) == 1


def test_release_lock_failure_does_not_override_committed_success():
    connection = Connection(fail_on_release=True)

    summary = MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog((), (), NOW)

    assert summary.created == 0
    assert connection.executions[-1][0].find("RELEASE_LOCK") >= 0
    assert connection.invalidated


def test_release_lock_failure_does_not_override_original_business_error():
    connection = Connection(fail_on_insert=True, fail_on_release=True)

    with pytest.raises(RuntimeError, match="^boom$"):
        MysqlWeRSSCatalogSyncRepo(Engine(connection)).sync_catalog(
            (WeRSSCatalogItem("MP1", "甲", True),), (), NOW
        )
