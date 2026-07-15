from __future__ import annotations

import re
from pathlib import Path


INIT_SQL = Path("sql/init.sql")
REQUEST_MIGRATION = Path(
    "sql/migrations/20260710_003_create_report_requests.sql"
)
LIFECYCLE_MIGRATION = Path(
    "sql/migrations/20260710_004_add_report_lifecycle.sql"
)

REQUEST_DEFINITIONS = (
    "id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '日报生成请求主键'",
    "idempotency_key VARCHAR(100) NOT NULL COMMENT '请求幂等键'",
    "report_type VARCHAR(20) NOT NULL COMMENT 'group/article/summary/all'",
    "report_date DATE NOT NULL COMMENT '日报业务日期'",
    "source_name VARCHAR(200) NULL COMMENT '可选群名或公众号名称'",
    "generation_trigger VARCHAR(20) NOT NULL COMMENT 'manual/automatic/compensation'",
    "data_cutoff_time DATETIME NOT NULL COMMENT '统计数据截止时间'",
    "requested_by VARCHAR(100) NOT NULL COMMENT 'admin/system'",
    "status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/partial_success/failed'",
    "worker_id VARCHAR(100) NULL COMMENT '领取请求的Worker'",
    "lease_expires_at DATETIME NULL COMMENT '运行租约截止时间'",
    "error_summary TEXT NULL COMMENT '安全失败摘要'",
    "create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "start_time DATETIME NULL COMMENT '开始时间'",
    "end_time DATETIME NULL COMMENT '结束时间'",
    "UNIQUE KEY uk_report_request_idempotency (idempotency_key)",
    "KEY idx_report_request_pending (status, create_time)",
    "KEY idx_report_request_date (report_date, report_type)",
)

LIFECYCLE_DEFINITIONS = (
    "report_status VARCHAR(20) NOT NULL DEFAULT 'final' COMMENT 'provisional/final'",
    "data_cutoff_time DATETIME NULL COMMENT '统计数据截止时间'",
    "generation_trigger VARCHAR(20) NOT NULL DEFAULT 'legacy' COMMENT 'manual/automatic/compensation/legacy'",
    "last_generated_by VARCHAR(100) NOT NULL DEFAULT 'system' COMMENT 'admin/system'",
)

REPORT_TABLES = (
    "wechat_group_daily_report",
    "wechat_article_daily_report",
)


def _table_block(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\s*"
        rf"\((?P<body>.*?)\)\s*ENGINE=InnoDB\s+DEFAULT\s+CHARSET=utf8mb4\s*;",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert match is not None, table
    return match.group(0)


def _normalized(sql: str) -> str:
    return re.sub(r"\s+", "", sql).lower()


def _assert_definitions(block: str, definitions: tuple[str, ...]) -> None:
    normalized_block = _normalized(block)
    for definition in definitions:
        assert _normalized(definition) in normalized_block, definition


def test_report_request_schema_is_complete_and_matches_init() -> None:
    request_sql = REQUEST_MIGRATION.read_text(encoding="utf-8")
    init_sql = INIT_SQL.read_text(encoding="utf-8")

    migration_block = _table_block(
        request_sql, "wechat_report_generation_request"
    )
    init_block = _table_block(init_sql, "wechat_report_generation_request")
    _assert_definitions(migration_block, REQUEST_DEFINITIONS)
    _assert_definitions(init_block, REQUEST_DEFINITIONS)
    assert _normalized(migration_block) == _normalized(init_block)


def test_daily_report_lifecycle_exists_in_init_and_migration() -> None:
    lifecycle_sql = LIFECYCLE_MIGRATION.read_text(encoding="utf-8")
    init_sql = INIT_SQL.read_text(encoding="utf-8")

    for table in REPORT_TABLES:
        _assert_definitions(
            _table_block(init_sql, table), LIFECYCLE_DEFINITIONS
        )
        for column in (
            "report_status",
            "data_cutoff_time",
            "generation_trigger",
            "last_generated_by",
        ):
            probe = re.compile(
                rf"FROM\s+information_schema\.COLUMNS\s+"
                rf"WHERE\s+TABLE_SCHEMA\s*=\s*DATABASE\(\)\s+"
                rf"AND\s+TABLE_NAME\s*=\s*'{table}'\s+"
                rf"AND\s+COLUMN_NAME\s*=\s*'{column}'",
                flags=re.IGNORECASE,
            )
            assert probe.search(lifecycle_sql), (table, column)
            assert re.search(
                rf"ALTER\s+TABLE\s+{table}\s+ADD\s+COLUMN\s+{column}\b",
                lifecycle_sql,
                flags=re.IGNORECASE,
            ), (table, column)

    for definition in LIFECYCLE_DEFINITIONS:
        escaped_definition = definition.replace("'", "''")
        assert _normalized(escaped_definition) in _normalized(lifecycle_sql)


def test_migrations_are_additive_and_history_backfill_is_cutoff_only() -> None:
    request_sql = REQUEST_MIGRATION.read_text(encoding="utf-8")
    lifecycle_sql = LIFECYCLE_MIGRATION.read_text(encoding="utf-8")
    combined = request_sql + lifecycle_sql

    for forbidden in (
        "DROP TABLE",
        "DROP COLUMN",
        "TRUNCATE TABLE",
        "DELETE FROM",
    ):
        assert forbidden not in combined.upper()

    updates = re.findall(
        r"UPDATE\s+\w+\s+SET\s+.*?\s+WHERE\s+.*?;",
        lifecycle_sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert {_normalized(update) for update in updates} == {
        _normalized(
            "UPDATE wechat_group_daily_report "
            "SET data_cutoff_time = generate_time "
            "WHERE data_cutoff_time IS NULL;"
        ),
        _normalized(
            "UPDATE wechat_article_daily_report "
            "SET data_cutoff_time = generate_time "
            "WHERE data_cutoff_time IS NULL;"
        ),
    }


def test_lifecycle_migration_uses_task_scoped_prepare_names() -> None:
    lifecycle_sql = LIFECYCLE_MIGRATION.read_text(encoding="utf-8")

    assert "@report_lifecycle_ddl" in lifecycle_sql
    assert "PREPARE report_lifecycle_stmt" in lifecycle_sql
    assert lifecycle_sql.count("DEALLOCATE PREPARE report_lifecycle_stmt") == 8
