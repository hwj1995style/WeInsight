from __future__ import annotations

from pathlib import Path


def test_init_sql_has_article_raw_table() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_raw" in sql
    assert "article_hash VARCHAR(64) NOT NULL" in sql
    assert "account_name VARCHAR(200) NOT NULL" in sql
    assert "title VARCHAR(500) NOT NULL" in sql
    assert "article_url TEXT NOT NULL" in sql
    assert "publish_time DATETIME NOT NULL" in sql
    assert "publish_date DATE NOT NULL" in sql
    assert "author VARCHAR(200) NULL" in sql
    assert "digest TEXT NULL" in sql
    assert "collect_batch_id VARCHAR(64) NULL" in sql
    assert "collect_time DATETIME NOT NULL" in sql
    assert "UNIQUE KEY uk_article_hash (article_hash)" in sql
    assert "KEY idx_article_account_publish (account_name, publish_time)" in sql
    assert "KEY idx_article_publish_date (publish_date)" in sql


def test_article_raw_migration_is_idempotent_and_isolated() -> None:
    migration = Path("sql/migrations/20260706_001_create_article_raw.sql")

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS wechat_article_raw" in sql
    assert "UNIQUE KEY uk_article_hash (article_hash)" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
