from __future__ import annotations

import re
from pathlib import Path


MIGRATION_NAME_PATTERN = re.compile(r"^\d{8}_\d{3}_[a-z0-9_]+\.sql$")


def test_sql_migrations_directory_and_names_are_ordered() -> None:
    migrations_dir = Path("sql/migrations")

    assert migrations_dir.exists()
    migration_files = sorted(migrations_dir.glob("*.sql"))
    assert migration_files
    assert [path.name for path in migration_files] == sorted(path.name for path in migration_files)
    for path in migration_files:
        assert MIGRATION_NAME_PATTERN.match(path.name), path.name


def test_group_analysis_quality_migration_is_idempotent_and_safe() -> None:
    migration = Path("sql/migrations/20260703_001_add_group_analysis_quality_fields.sql")
    sql = migration.read_text(encoding="utf-8")

    assert "information_schema.COLUMNS" in sql
    assert "ALTER TABLE wechat_group_msg_analysis" in sql
    for column in ["region_hits", "category_hits", "opportunity_hits", "opportunity_score"]:
        assert column in sql
        assert f"COLUMN_NAME = '{column}'" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
    assert "DELETE FROM" not in sql.upper()
    assert "wechat_article_process_task" not in sql


def test_init_sql_and_migrations_cover_current_group_analysis_schema() -> None:
    init_sql = Path("sql/init.sql").read_text(encoding="utf-8")
    migration_sql = Path("sql/migrations/20260703_001_add_group_analysis_quality_fields.sql").read_text(
        encoding="utf-8"
    )

    for column in ["region_hits", "category_hits", "opportunity_hits", "opportunity_score"]:
        assert column in init_sql
        assert column in migration_sql


def test_readme_documents_database_init_and_upgrade_order() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "sql/init.sql" in readme
    assert "sql/migrations/" in readme
    assert "YYYYMMDD_NNN" in readme
    assert "按文件名顺序执行" in readme


def test_werss_catalog_migration_is_idempotent_and_preserves_history() -> None:
    sql = Path("sql/migrations/20260713_001_add_werss_catalog_state.sql").read_text(
        encoding="utf-8"
    )

    assert sql.count("information_schema.COLUMNS") == 4
    assert "information_schema.STATISTICS" in sql
    for column in (
        "werss_source_id",
        "upstream_status",
        "upstream_last_seen_at",
        "upstream_missing_at",
    ):
        assert f"COLUMN_NAME = '{column}'" in sql
    assert "INDEX_NAME = 'uk_public_account_werss_source_id'" in sql
    for destructive in ("DROP TABLE", "TRUNCATE TABLE", "DELETE FROM"):
        assert destructive not in sql.upper()


def test_system_job_singleton_migration_is_idempotent_and_preserves_history() -> None:
    path = Path("sql/migrations/20260713_004_system_article_job_singleton.sql")
    sql = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS wechat_system_job_coordination" in sql
    assert "INSERT IGNORE INTO wechat_system_job_coordination" in sql
    assert "information_schema.COLUMNS" in sql
    assert "information_schema.STATISTICS" in sql
    assert "ADD COLUMN managed_key" in sql
    assert "ADD UNIQUE KEY uk_collection_job_managed_key" in sql
    assert "SET managed_key = 'article_global'" in sql
    assert "SET status = 'stop_requested', next_run_at = NULL" in sql
    for destructive in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE"):
        assert destructive not in sql.upper()


def test_legacy_article_daily_report_task_migration_retires_without_deleting() -> None:
    path = Path(
        "sql/migrations/20260716_001_retire_legacy_article_daily_report_tasks.sql"
    )
    sql = path.read_text(encoding="utf-8")

    assert "UPDATE wechat_article_process_task" in sql
    assert "task_type = 'article_daily_report'" in sql
    assert "status = 'success'" in sql
    assert "status IN ('pending', 'running', 'failed')" in sql
    for destructive in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE"):
        assert destructive not in sql.upper()


def test_deleted_job_source_reference_migration_is_idempotent_and_preserves_history() -> None:
    path = Path(
        "sql/migrations/20260717_001_release_deleted_job_source_references.sql"
    )
    sql = path.read_text(encoding="utf-8")

    assert "information_schema.TABLE_CONSTRAINTS" in sql
    assert "DROP CHECK ck_job_target_exactly_one" in sql
    assert "ADD CONSTRAINT ck_job_target_at_most_one" in sql
    assert "CHECK (group_config_id IS NULL OR article_config_id IS NULL)" in sql
    assert "DROP FOREIGN KEY" not in sql
    assert "ON DELETE SET NULL" not in sql
    for destructive in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE"):
        assert destructive not in sql.upper()


def test_job_target_activation_migration_is_additive_and_idempotent() -> None:
    path = Path(
        "sql/migrations/20260717_002_add_job_target_activation.sql"
    )
    sql = path.read_text(encoding="utf-8")

    assert "information_schema.COLUMNS" in sql
    assert "ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1" in sql
    assert "information_schema.STATISTICS" in sql
    assert "ADD KEY idx_job_target_active (job_id, is_active)" in sql
    for destructive in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE"):
        assert destructive not in sql.upper()
