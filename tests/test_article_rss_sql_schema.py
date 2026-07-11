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
