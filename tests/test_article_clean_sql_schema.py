from __future__ import annotations

from pathlib import Path


def test_init_sql_has_article_clean_table() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_clean" in sql
    assert "article_hash VARCHAR(64) NOT NULL" in sql
    assert "account_name VARCHAR(200) NOT NULL" in sql
    assert "title VARCHAR(500) NOT NULL" in sql
    assert "article_url TEXT NOT NULL" in sql
    assert "publish_time DATETIME NULL" in sql
    assert "author VARCHAR(200) NULL" in sql
    assert "digest TEXT NULL" in sql
    assert "content_length INT DEFAULT 0" in sql
    assert "parse_time DATETIME NOT NULL" in sql
    assert "parse_version VARCHAR(20) DEFAULT 'v1'" in sql
    assert "UNIQUE KEY uk_clean_article_hash (article_hash)" in sql
    assert "KEY idx_article_clean_account_publish (account_name, publish_time)" in sql
    assert "KEY idx_article_clean_parse_time (parse_time)" in sql


def test_article_clean_migration_is_idempotent_and_isolated() -> None:
    migration = Path("sql/migrations/20260706_002_create_article_clean.sql")

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS wechat_article_clean" in sql
    assert "UNIQUE KEY uk_clean_article_hash (article_hash)" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
