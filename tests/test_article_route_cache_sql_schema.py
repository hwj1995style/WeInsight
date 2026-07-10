from __future__ import annotations

from pathlib import Path

from app.storage.schema import read_init_sql


MIGRATION = Path("sql/migrations/20260707_001_create_article_route_cache.sql")


def test_article_route_cache_table_exists_in_init_sql() -> None:
    sql = read_init_sql()

    assert "CREATE TABLE IF NOT EXISTS wechat_article_route_cache" in sql
    assert "account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称'" in sql
    assert "route_type VARCHAR(50) NOT NULL COMMENT '取链入口类型'" in sql
    assert "link_extract_type VARCHAR(50) NOT NULL COMMENT '链接提取方式'" in sql
    assert "UNIQUE KEY uk_article_route_account (account_name)" in sql
    assert "KEY idx_article_route_status (cache_status, failure_count)" in sql


def test_article_route_cache_migration_is_idempotent_and_isolated() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_route_cache" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql
