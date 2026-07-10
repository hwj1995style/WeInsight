from __future__ import annotations

import re
from pathlib import Path

import pytest


MIGRATION = Path("sql/migrations/20260710_002_create_collection_control.sql")
INIT_SQL = Path("sql/init.sql")
TABLE_COLUMNS = {
    "wechat_collection_job": (
        "id", "job_name", "pipeline_type", "effective_start_at",
        "effective_end_at", "daily_window_start", "daily_window_end",
        "interval_seconds", "status", "next_run_at", "stop_requested_at",
        "stop_requested_by", "deleted_at", "deleted_by", "version",
        "create_time", "update_time",
    ),
    "wechat_collection_job_target": (
        "id", "job_id", "group_config_id", "article_config_id",
        "target_name_snapshot", "priority_snapshot", "config_snapshot_json",
        "create_time",
    ),
    "wechat_collection_job_run": (
        "id", "job_id", "scheduled_at", "status", "worker_id",
        "lease_expires_at", "start_time", "end_time", "target_total_count",
        "target_success_count", "target_failed_count", "error_code",
        "error_summary", "create_time", "update_time",
    ),
    "wechat_collection_job_target_run": (
        "id", "run_id", "job_target_id", "batch_id", "status", "stage",
        "read_count", "insert_count", "duplicate_count", "skipped_count",
        "error_code", "error_summary", "screenshot_path", "start_time",
        "end_time", "create_time", "update_time",
    ),
    "wechat_collection_job_event": (
        "id", "job_id", "run_id", "target_run_id", "worker_id", "level",
        "event_type", "stage", "message", "metrics_json", "actor_type",
        "actor_name", "create_time",
    ),
    "wechat_worker_heartbeat": (
        "worker_id", "worker_type", "hostname", "process_id", "version",
        "status", "last_heartbeat_at", "start_time", "last_error_summary",
    ),
    "wechat_client_health_check": (
        "id", "worker_id", "hostname", "status", "detected_version",
        "consecutive_failure_count", "message", "checked_at",
    ),
}


def _table_block(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\)\s*ENGINE=InnoDB\s+DEFAULT CHARSET=utf8mb4;",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert match is not None, table
    return match.group(0)


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _assert_schema(sql: str) -> None:
    upper = sql.upper()
    for forbidden in ("DROP TABLE", "TRUNCATE TABLE", "DELETE FROM"):
        assert forbidden not in upper
    for table, columns in TABLE_COLUMNS.items():
        block = _table_block(sql, table)
        for column in columns:
            assert re.search(rf"(?m)^\s*{column}\s+", block), (table, column)

    required_fragments = (
        "CONSTRAINT ck_job_target_exactly_one CHECK",
        "CONSTRAINT fk_job_target_group FOREIGN KEY (group_config_id)",
        "CONSTRAINT fk_job_target_article FOREIGN KEY (article_config_id)",
        "UNIQUE KEY uk_job_schedule (job_id, scheduled_at)",
        "KEY idx_collection_event_run (run_id, id)",
        "KEY idx_collection_event_job_time (job_id, create_time)",
        "PRIMARY KEY (worker_id)",
        "KEY idx_client_health_checked (checked_at)",
        "KEY idx_client_health_status (status, checked_at)",
    )
    for fragment in required_fragments:
        assert fragment in sql
    assert upper.count("ON DELETE RESTRICT") >= 6


def test_collection_control_schema_is_complete_additive_and_synchronized() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    init_sql = INIT_SQL.read_text(encoding="utf-8")

    _assert_schema(migration)
    _assert_schema(init_sql)
    for table in TABLE_COLUMNS:
        assert _normalized(_table_block(migration, table)) == _normalized(
            _table_block(init_sql, table)
        )


@pytest.mark.parametrize(
    "fragment",
    [
        "group_config_id BIGINT NULL COMMENT '微信群配置主键'",
        "article_config_id BIGINT NULL COMMENT '公众号配置主键'",
        "UNIQUE KEY uk_job_schedule (job_id, scheduled_at)",
        "CONSTRAINT fk_job_target_group FOREIGN KEY (group_config_id)",
        "KEY idx_collection_event_run (run_id, id)",
    ],
)
def test_schema_validation_rejects_removed_critical_constraints(fragment: str) -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert migration.count(fragment) == 1

    with pytest.raises(AssertionError):
        _assert_schema(migration.replace(fragment, "", 1))
