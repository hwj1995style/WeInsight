from pathlib import Path


def test_werss_catalog_migration_has_state_columns_and_unique_id() -> None:
    sql = Path("sql/migrations/20260713_001_add_werss_catalog_state.sql").read_text("utf-8")
    for name in (
        "werss_source_id",
        "upstream_status",
        "upstream_last_seen_at",
        "upstream_missing_at",
    ):
        assert name in sql
    assert "uk_public_account_werss_source_id" in sql
    assert "DROP TABLE" not in sql.upper()


def test_init_schema_has_werss_catalog_state() -> None:
    sql = Path("sql/init.sql").read_text("utf-8")
    for name in (
        "werss_source_id",
        "upstream_status",
        "upstream_last_seen_at",
        "upstream_missing_at",
        "uk_public_account_werss_source_id",
    ):
        assert name in sql
