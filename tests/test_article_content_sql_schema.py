from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_content_metadata_migration_is_idempotent_and_stores_no_body():
    sql = (ROOT / "sql/migrations/20260712_001_add_article_content_metadata.sql").read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "drop procedure if exists migrate_20260712_001" in lowered
    assert "information_schema.columns" in lowered
    assert "add column if not exists" not in lowered
    for column in ("content_locator", "content_locator_type", "content_source", "content_hash", "content_fetch_status"):
        assert column in lowered
    assert "content_html" not in lowered
    assert "content_text" not in lowered


def test_init_schema_has_metadata_but_no_article_body_columns():
    sql = (ROOT / "sql/init.sql").read_text(encoding="utf-8").lower()
    for column in ("content_locator", "content_locator_type", "content_source", "content_hash", "content_fetch_status"):
        assert column in sql
    assert "content_html" not in sql
    assert "content_text" not in sql
