from pathlib import Path


def test_article_rss_migration_adds_nullable_feed_url_and_source_fields() -> None:
    sql = Path("sql/migrations/20260711_001_add_article_rss_source.sql").read_text("utf-8")
    for fragment in (
        "feed_url TEXT NULL",
        "source_type VARCHAR(20) NOT NULL DEFAULT 'rss'",
        "request_timeout_seconds INT NOT NULL DEFAULT 30",
        "last_feed_etag VARCHAR(500) NULL",
        "last_feed_modified VARCHAR(100) NULL",
        "last_error_code VARCHAR(100) NULL",
        "UNIQUE KEY uk_public_account_feed_url",
    ):
        assert fragment in sql


def test_article_rss_migration_is_retry_safe_and_uses_full_url_hash_uniqueness() -> None:
    migration = Path("sql/migrations/20260711_001_add_article_rss_source.sql").read_text("utf-8")
    init_sql = Path("sql/init.sql").read_text("utf-8")
    assert "information_schema.COLUMNS" in migration
    assert "information_schema.STATISTICS" in migration
    assert "feed_url_hash BINARY(32)" in migration
    assert "UNHEX(SHA2(feed_url, 256))" in migration
    assert "feed_url(255)" not in migration
    assert "feed_url_hash BINARY(32)" in init_sql
    assert "UNIQUE KEY uk_public_account_feed_url_hash (feed_url_hash)" in init_sql
    assert "feed_url(255)" not in init_sql
    helper = "migrate_20260711_001"
    assert migration.index(f"DROP PROCEDURE IF EXISTS {helper}") < migration.index(f"CREATE PROCEDURE {helper}")
    assert migration.index(f"CREATE PROCEDURE {helper}") < migration.index(f"CALL {helper}()")
    assert migration.index(f"CALL {helper}()") < migration.rindex(f"DROP PROCEDURE {helper}")


def test_drop_rpa_migration_helper_can_recover_after_failed_call() -> None:
    migration = Path("sql/migrations/20260711_003_drop_article_rpa_state.sql").read_text("utf-8")
    helper = "migrate_20260711_003_feed_hash"
    assert migration.index(f"DROP PROCEDURE IF EXISTS {helper}") < migration.index(f"CREATE PROCEDURE {helper}")
    assert migration.index(f"CREATE PROCEDURE {helper}") < migration.index(f"CALL {helper}()")
    assert migration.index(f"CALL {helper}()") < migration.rindex(f"DROP PROCEDURE {helper}")


def test_article_rss_init_schema_matches_migration() -> None:
    sql = Path("sql/init.sql").read_text("utf-8")
    for fragment in ("feed_url TEXT NULL", "source_type VARCHAR(20) NOT NULL DEFAULT 'rss'", "request_timeout_seconds INT NOT NULL DEFAULT 30", "UNIQUE KEY uk_public_account_feed_url"):
        assert fragment in sql


def test_rss_collect_log_metrics_exist_in_init_and_idempotent_migration() -> None:
    init = Path("sql/init.sql").read_text("utf-8")
    article_log = init.split("CREATE TABLE IF NOT EXISTS wechat_article_collect_log", 1)[1].split(") ENGINE=InnoDB", 1)[0]
    migration = Path("sql/migrations/20260711_002_add_rss_collect_log_metrics.sql").read_text("utf-8")
    for column in ("feed_item_count", "duplicate_count", "invalid_count", "http_status", "elapsed_ms"):
        assert column in article_log
        assert f"COLUMN_NAME='{column}'" in migration
        assert f"ADD COLUMN {column}" in migration
    assert "ADD COLUMN IF NOT EXISTS" not in migration
    assert "DROP PROCEDURE IF EXISTS migrate_20260711_002" in migration
    assert "CREATE PROCEDURE migrate_20260711_002" in migration
    assert "CALL migrate_20260711_002()" in migration
    assert "DROP PROCEDURE migrate_20260711_002" in migration
