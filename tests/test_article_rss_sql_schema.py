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
        assert f"ADD COLUMN IF NOT EXISTS {column}" in migration
