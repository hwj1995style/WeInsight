from __future__ import annotations

from pathlib import Path


def test_init_sql_has_public_account_config_table() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_public_account_config" in sql
    assert "account_name VARCHAR(200) NOT NULL" in sql
    assert "account_type VARCHAR(50) NOT NULL DEFAULT 'subscription'" in sql
    assert "poll_interval_minutes INT DEFAULT 60" in sql
    assert "daily_window_start TIME NOT NULL DEFAULT '07:30:00'" in sql
    assert "daily_window_end TIME NOT NULL DEFAULT '19:30:00'" in sql
    assert "max_articles_per_round INT DEFAULT 5" in sql
    assert "collect_today_only TINYINT DEFAULT 1" in sql
    assert "dedup_key VARCHAR(50) DEFAULT 'article_hash'" in sql
    assert "UNIQUE KEY uk_public_account_name (account_name)" in sql


def test_public_account_config_migration_is_idempotent_and_isolated() -> None:
    migration = Path("sql/migrations/20260703_002_create_public_account_config.sql")

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS wechat_public_account_config" in sql
    assert "uk_public_account_name" in sql
    assert "wechat_group_config" not in sql
    assert "wechat_group_process_task" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
