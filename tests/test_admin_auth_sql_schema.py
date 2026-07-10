from pathlib import Path


def test_admin_auth_schema_exists_in_init_and_migration() -> None:
    init_sql = Path("sql/init.sql").read_text(encoding="utf-8")
    migration_sql = Path(
        "sql/migrations/20260710_001_create_admin_auth.sql"
    ).read_text(encoding="utf-8")

    for sql in (init_sql, migration_sql):
        assert "CREATE TABLE IF NOT EXISTS weinsight_admin_user" in sql
        assert "CREATE TABLE IF NOT EXISTS weinsight_admin_session" in sql
        assert "password_hash" in sql
        assert "token_hash" in sql
        assert "csrf_token_hash" in sql
        assert "locked_until" in sql
        assert "expires_at" in sql
        assert "DROP TABLE" not in sql.upper()
        assert "TRUNCATE TABLE" not in sql.upper()
