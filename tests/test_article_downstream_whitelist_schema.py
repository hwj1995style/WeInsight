from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_downstream_whitelist_schema_is_persistent_safe_default_and_mysql84_idempotent():
    init = (ROOT / "sql/init.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql/migrations/20260712_002_add_article_downstream_whitelist.sql").read_text(encoding="utf-8")
    assert "downstream_clean_enabled TINYINT NOT NULL DEFAULT 0" in init
    assert "information_schema.COLUMNS" in migration
    assert "DROP PROCEDURE IF EXISTS migrate_20260712_002" in migration
    assert "ADD COLUMN IF NOT EXISTS" not in migration
