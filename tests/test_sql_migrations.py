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
