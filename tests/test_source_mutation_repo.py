from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from app.services.source_management_service import SourceManagementService
from app.storage.article_config_repo import MysqlArticleAccountConfigRepo
from app.storage.group_repo import MysqlGroupConfigRepo
from app.storage.source_mutation_repo import (
    MysqlSourceMutationRepo,
    MysqlSourceWriteGuard,
    SourceGuardDisabledError,
    _source_creation_config,
)
from app.storage.collection_runtime_repo import ClaimedTarget
from app.workers.collector_worker import _article_target
from app.storage.source_reference_repo import MysqlSourceReferenceRepo


class Result:
    def __init__(self, *, rows=None, scalar=None, rowcount=1) -> None:
        self.rows = rows or []
        self.scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return next(self.results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, results) -> None:
        self.connection = Connection(results)
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


def test_article_source_creation_snapshot_reaches_rss_runner_target() -> None:
    row = {
        "account_type": "subscription", "feed_url": "http://127.0.0.1:8001/feed.xml",
        "source_type": "rss", "request_timeout_seconds": 25,
        "collect_today_only": True, "daily_window_end": "19:30:00",
        "daily_window_start": "07:30:00", "dedup_key": "article_hash",
        "max_articles_per_round": 5, "poll_interval_minutes": 10, "remark": None,
    }
    snapshot = _source_creation_config("article", row)
    target = _article_target(ClaimedTarget(
        job_target_id=3, source_id=9, source_name="行业观察", priority=1,
        config_snapshot_json=json.dumps(snapshot),
    ))
    assert target.feed_url == row["feed_url"]
    assert target.source_type == "rss"
    assert target.request_timeout_seconds == 25


def test_group_rename_locks_and_rechecks_in_one_transaction() -> None:
    engine = Engine(
        [
            Result(rows=[{"id": 7, "source_name": "旧群名", "enabled": 1}]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(),
        ]
    )
    repo = MysqlSourceMutationRepo(engine)

    repo.update_group(
        7,
        group_name="新群名",
        priority=1,
        poll_interval_seconds=30,
        backtrack_pages=1,
        extra_backtrack_pages=3,
        is_core_group=True,
        remark=None,
    )

    assert engine.begin_count == 1
    statements = [sql for sql, _ in engine.connection.executions]
    assert "FOR UPDATE" in statements[0]
    assert "wechat_collection_job_target" in statements[1]
    assert "FOR SHARE" in statements[1]
    assert "wechat_group_msg_raw" in statements[2]
    assert "FOR SHARE" in statements[2]
    assert "UPDATE wechat_group_config" in statements[-1]
    assert "WHERE id = :source_id" in statements[-1]


def test_delete_detaches_only_deleted_job_targets_before_deleting_source() -> None:
    engine = Engine(
        [
            Result(rows=[{"id": 7, "source_name": "旧群名", "enabled": 0}]),
            Result(rows=[]),
            Result(),
            Result(),
        ]
    )

    MysqlSourceMutationRepo(engine).delete_group(7)

    assert engine.begin_count == 1
    statements = [sql for sql, _ in engine.connection.executions]
    assert "FOR UPDATE" in statements[0]
    assert "job.status IN" not in statements[1]
    assert "job.status <> 'deleted'" in statements[1]
    assert "FOR SHARE" in statements[1]
    assert "UPDATE wechat_collection_job_target AS target" in statements[2]
    assert "SET target.group_config_id = NULL" in statements[2]
    assert "job.status = 'deleted'" in statements[2]
    assert "DELETE FROM wechat_group_config" in statements[3]
    assert "enabled = 0" in statements[3]


def test_article_rename_checks_article_raw_with_current_locking_read() -> None:
    engine = Engine(
        [
            Result(rows=[{"id": 9, "source_name": "旧账号", "enabled": 1}]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(rows=[]),
            Result(),
        ]
    )

    MysqlSourceMutationRepo(engine).update_article(
        9,
        account_name="新账号",
        account_type="subscription",
        priority=1,
        poll_interval_minutes=10,
        daily_window_start="07:30",
        daily_window_end="19:30",
        max_articles_per_round=5,
        collect_today_only=True,
        remark=None,
    )

    statements = [sql for sql, _ in engine.connection.executions]
    assert "FOR UPDATE" in statements[0]
    assert "wechat_article_raw" in statements[2]
    assert "FOR SHARE" in statements[2]
    assert "UPDATE wechat_public_account_config" in statements[-1]


def test_service_auto_uses_transaction_repo_for_real_mysql_repos() -> None:
    engine = Engine(
        [
            Result(rows=[{"id": 7, "source_name": "核心群A", "enabled": 1}]),
            Result(),
        ]
    )
    service = SourceManagementService(
        MysqlGroupConfigRepo(engine),
        MysqlArticleAccountConfigRepo(engine),
        MysqlSourceReferenceRepo(engine),
    )

    service.set_group_enabled(7, True)

    assert engine.begin_count == 1
    assert "FOR UPDATE" in engine.connection.executions[0][0]


def test_real_mysql_same_state_enable_and_disable_are_idempotent() -> None:
    engine = Engine(
        [
            Result(rows=[{"id": 7, "source_name": "核心群A", "enabled": 0}]),
            Result(rows=[{
                "id": 9, "account_name": "行业观察", "account_type": "subscription",
                "feed_url": "https://example.com/industry.xml", "source_type": "rss",
                "request_timeout_seconds": 30, "enabled": 1, "priority": 2,
                "poll_interval_minutes": 10, "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00", "max_articles_per_round": 5,
                "collect_today_only": 1, "dedup_key": "article_hash",
                "last_success_collect_time": None, "last_feed_etag": None,
                "last_feed_modified": None, "last_error_code": None, "remark": None,
            }]),
            Result(rows=[{"id": 9, "source_name": "行业观察", "enabled": 1}]),
        ]
    )
    service = SourceManagementService(
        MysqlGroupConfigRepo(engine),
        MysqlArticleAccountConfigRepo(engine),
        MysqlSourceReferenceRepo(engine),
    )

    service.set_group_enabled(7, False)
    service.set_article_enabled(9, True)

    assert engine.begin_count == 3
    assert len(engine.connection.executions) == 3
    assert all("FOR UPDATE" in engine.connection.executions[index][0] for index in (0, 2))


def test_job_target_guard_locks_enabled_source_in_callers_transaction() -> None:
    connection = Connection(
        [Result(rows=[{"id": 7, "source_name": "核心群A", "enabled": 1}])]
    )

    record = MysqlSourceWriteGuard().lock_for_job_target(
        connection, "group", 7
    )

    assert record.source_name == "核心群A"
    sql, params = connection.executions[0]
    assert "FROM wechat_group_config" in sql
    assert "WHERE id = :source_id" in sql
    assert "FOR SHARE" in sql
    assert params == {"source_id": 7}


def test_job_target_guard_rejects_disabled_source() -> None:
    connection = Connection(
        [Result(rows=[{"id": 9, "source_name": "行业观察", "enabled": 0}])]
    )
    with pytest.raises(SourceGuardDisabledError):
        MysqlSourceWriteGuard().lock_for_job_target(connection, "article", 9)


def test_job_creation_guard_exclusively_locks_complete_group_config() -> None:
    connection = Connection(
        [
            Result(
                rows=[
                    {
                        "id": 7,
                        "source_name": "核心群A",
                        "enabled": 1,
                        "priority": 2,
                        "poll_interval_seconds": 45,
                        "backtrack_pages": 4,
                        "extra_backtrack_pages": 8,
                        "is_core_group": 1,
                        "remark": "重点",
                    }
                ]
            )
        ]
    )

    record = MysqlSourceWriteGuard().lock_for_job_creation(
        connection, "group", 7
    )

    assert record.id == 7
    assert record.source_name == "核心群A"
    assert record.priority == 2
    assert record.config == {
        "backtrack_pages": 4,
        "extra_backtrack_pages": 8,
        "is_core_group": True,
        "poll_interval_seconds": 45,
        "remark": "重点",
    }
    sql, params = connection.executions[0]
    assert "FROM wechat_group_config" in sql
    assert "FOR UPDATE" in sql
    assert "backtrack_pages" in sql
    assert params == {"source_id": 7}


def test_job_creation_guard_rejects_disabled_complete_article_config() -> None:
    connection = Connection(
        [
            Result(
                rows=[
                    {
                        "id": 9,
                        "source_name": "行业观察",
                        "enabled": 0,
                        "priority": 3,
                        "account_type": "subscription",
                        "poll_interval_minutes": 10,
                        "daily_window_start": "07:30:00",
                        "daily_window_end": "19:30:00",
                        "max_articles_per_round": 5,
                        "collect_today_only": 1,
                        "dedup_key": "article_hash",
                        "remark": None,
                    }
                ]
            )
        ]
    )

    with pytest.raises(SourceGuardDisabledError):
        MysqlSourceWriteGuard().lock_for_job_creation(
            connection, "article", 9
        )

    assert "FOR UPDATE" in connection.executions[0][0]


@pytest.mark.parametrize(
    ("source_type", "source_name", "table", "column"),
    [
        ("group", "核心群A", "wechat_group_config", "group_name"),
        ("article", "行业观察", "wechat_public_account_config", "account_name"),
    ],
)
def test_history_guard_locks_current_name_in_callers_transaction(
    source_type, source_name, table, column
) -> None:
    connection = Connection(
        [Result(rows=[{"id": 1, "source_name": source_name, "enabled": 1}])]
    )

    MysqlSourceWriteGuard().lock_for_history_write(
        connection, source_type, source_name
    )

    sql, params = connection.executions[0]
    assert f"FROM {table}" in sql
    assert f"WHERE {column} = :source_name" in sql
    assert "FOR SHARE" in sql
    assert params == {"source_name": source_name}
