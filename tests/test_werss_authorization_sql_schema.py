from pathlib import Path


def test_werss_authorization_tables_have_state_and_deduplicated_notice_keys() -> None:
    migration = Path(
        "sql/migrations/20260716_001_create_werss_authorization_management.sql"
    ).read_text("utf-8")
    init = Path("sql/init.sql").read_text("utf-8")

    for text in (migration, init):
        assert "CREATE TABLE IF NOT EXISTS wechat_werss_authorization_state" in text
        assert "CREATE TABLE IF NOT EXISTS wechat_werss_authorization_notice" in text
        assert "CREATE TABLE IF NOT EXISTS wechat_werss_authorization_settings" in text
        assert "authorization_version" in text
        assert "uk_werss_auth_notice_version_type" in text
        assert "last_error_code" in text
        assert "werss_password_encrypted BLOB" in text
        assert "smtp_password_encrypted BLOB" in text
