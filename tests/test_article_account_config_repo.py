from __future__ import annotations

import re
from datetime import datetime

import pytest

from app.storage.article_config_repo import ArticleAccountConfigRecord, MysqlArticleAccountConfigRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []
        self.rowcount = 1
        self.lastrowid = 9

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return FakeResult(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, rows=None) -> None:
        self.connection = FakeConnection(rows)

    def begin(self):
        return self.connection


def test_record_maps_werss_state() -> None:
    now = datetime(2026, 7, 13, 9, 0)
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 60,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": None,
                "werss_source_id": "MP_WXS_1",
                "upstream_status": "active",
                "upstream_last_seen_at": now,
                "upstream_missing_at": None,
            }
        ]
    )

    record = MysqlArticleAccountConfigRepo(engine).list_accounts()[0]

    assert (record.werss_source_id, record.upstream_status) == ("MP_WXS_1", "active")
    assert record.upstream_last_seen_at == now
    assert record.upstream_missing_at is None
    sql, _ = engine.connection.executions[0]
    for column in (
        "werss_source_id",
        "upstream_status",
        "upstream_last_seen_at",
        "upstream_missing_at",
    ):
        assert column in sql


def test_mysql_article_account_config_repo_upserts_account_config() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAccountConfigRepo(engine)

    repo.upsert_account_config(
        account_name="行业观察",
        account_type="subscription",
        feed_url="http://werss.local/feed/industry.xml",
        source_type="rss",
        enabled=True,
        priority=2,
        poll_interval_minutes=60,
        request_timeout_seconds=30,
        daily_window_start="07:30",
        daily_window_end="19:30",
        max_articles_per_round=5,
        collect_today_only=True,
        dedup_key="article_hash",
        remark="授权账号",
    )

    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_public_account_config" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "wechat_group_config" not in sql
    assert params["account_name"] == "行业观察"
    assert params["enabled"] == 1
    assert params["poll_interval_minutes"] == 60
    assert params["daily_window_start"] == "07:30"
    assert params["daily_window_end"] == "19:30"
    assert params["collect_today_only"] == 1
    columns = re.search(r"INSERT INTO wechat_public_account_config\s*\((.*?)\)\s*VALUES", sql, re.S).group(1)
    values = re.search(r"\)\s*VALUES\s*\((.*?)\)\s*ON DUPLICATE", sql, re.S).group(1)
    expected = ["account_name", "account_type", "feed_url", "source_type", "enabled", "priority", "poll_interval_minutes", "request_timeout_seconds", "daily_window_start", "daily_window_end", "max_articles_per_round", "collect_today_only", "dedup_key", "remark"]
    assert [part.strip() for part in columns.split(",")] == expected
    assert [part.strip() for part in values.split(",")] == [f":{name}" for name in expected]


def test_repo_persists_validated_downstream_clean_allowlist_flag() -> None:
    engine = FakeEngine()
    MysqlArticleAccountConfigRepo(engine).set_downstream_clean_enabled("湖南三尖农牧公司", True)
    sql, params = engine.connection.executions[0]
    assert "downstream_clean_enabled = :enabled" in sql
    assert params == {"account_name": "湖南三尖农牧公司", "enabled": 1}


def test_repo_fails_when_downstream_account_does_not_exist() -> None:
    engine = FakeEngine()
    missing = FakeResult([])
    missing.rowcount = 0
    engine.connection.execute = lambda statement, params=None: missing
    with pytest.raises(LookupError, match="account not found"):
        MysqlArticleAccountConfigRepo(engine).set_downstream_clean_enabled("不存在", True)


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_repo_rejects_non_boolean_downstream_flag(value) -> None:
    with pytest.raises(ValueError, match="boolean"):
        MysqlArticleAccountConfigRepo(FakeEngine()).set_downstream_clean_enabled("湖南三尖农牧公司", value)


def test_mysql_article_account_config_repo_creates_without_name_upsert() -> None:
    engine = FakeEngine()

    source_id = MysqlArticleAccountConfigRepo(engine).create_account_config(
        account_name="行业观察",
        account_type="subscription",
        feed_url="http://werss.local/feed/industry.xml",
        source_type="rss",
        enabled=True,
        priority=2,
        poll_interval_minutes=10,
        request_timeout_seconds=30,
        daily_window_start="07:30",
        daily_window_end="19:30",
        max_articles_per_round=5,
        collect_today_only=True,
        dedup_key="article_hash",
        remark=None,
    )

    assert source_id == 9
    sql, _ = engine.connection.executions[0]
    assert "INSERT INTO wechat_public_account_config" in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql


def test_mysql_article_account_config_repo_lists_accounts() -> None:
    last_success = datetime(2026, 7, 3, 8, 30)
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "feed_url": "https://example.com/industry.xml",
                "source_type": "rss",
                "request_timeout_seconds": 45,
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 60,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": last_success,
                "remark": "授权账号",
            }
        ]
    )
    repo = MysqlArticleAccountConfigRepo(engine)

    accounts = repo.list_accounts()

    assert accounts == [
            ArticleAccountConfigRecord(
                account_name="行业观察",
                account_type="subscription",
                feed_url="https://example.com/industry.xml",
                source_type="rss",
                request_timeout_seconds=45,
            priority=2,
            poll_interval_minutes=60,
            daily_window_start="07:30:00",
            daily_window_end="19:30:00",
            max_articles_per_round=5,
            enabled=True,
            collect_today_only=True,
            dedup_key="article_hash",
            last_success_collect_time=last_success,
            remark="授权账号",
            id=9,
        )
    ]
    sql, _ = engine.connection.executions[0]
    assert "FROM wechat_public_account_config" in sql
    assert "ORDER BY priority ASC" in sql
    assert "wechat_group_config" not in sql
    assert re.search(r"SELECT\s+id\s*,", sql)


def test_mysql_article_account_config_repo_pages_with_limit_and_offset() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 10,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": None,
            }
        ]
    )

    accounts = MysqlArticleAccountConfigRepo(engine).list_accounts_page(
        limit=11, offset=20
    )

    assert accounts[0].id == 9
    sql, params = engine.connection.executions[0]
    assert "LIMIT :limit" in sql
    assert "OFFSET :offset" in sql
    assert params == {"limit": 11, "offset": 20}


def test_mysql_article_config_repo_lists_enabled_job_choices_with_sql_limit() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 10,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": None,
            }
        ]
    )

    accounts = MysqlArticleAccountConfigRepo(engine).list_enabled_articles_for_job(
        limit=100
    )

    assert accounts[0].id == 9
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_public_account_config" in sql
    assert "WHERE enabled = 1" in sql
    assert "ORDER BY priority ASC, account_name ASC, id ASC" in sql
    assert "LIMIT :limit" in sql
    assert "OFFSET" not in sql
    assert params == {"limit": 100}


@pytest.mark.parametrize("limit", [0, 101, True, "10"])
def test_mysql_article_config_repo_rejects_invalid_job_choice_limit(limit) -> None:
    engine = FakeEngine()

    with pytest.raises(ValueError, match="limit"):
        MysqlArticleAccountConfigRepo(engine).list_enabled_articles_for_job(
            limit=limit
        )

    assert engine.connection.executions == []


def test_mysql_article_account_config_repo_lists_due_accounts_from_article_config_only() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "feed_url": "https://example.com/industry.xml",
                "source_type": "rss",
                "request_timeout_seconds": 45,
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 60,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": "授权账号",
            }
        ]
    )
    repo = MysqlArticleAccountConfigRepo(engine)

    accounts = repo.list_due_accounts(now=datetime(2026, 7, 6, 9, 0), limit=1)

    assert accounts[0].account_name == "行业观察"
    assert accounts[0].feed_url == "https://example.com/industry.xml"
    assert accounts[0].source_type == "rss"
    assert accounts[0].request_timeout_seconds == 45
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_public_account_config" in sql
    assert "enabled = 1" in sql
    assert "TIME(:now)" in sql
    assert "TIMESTAMPDIFF(MINUTE" in sql
    assert "ORDER BY priority ASC" in sql
    assert "LIMIT :limit" in sql
    assert re.search(r"SELECT\s+id\s*,", sql)
    assert "wechat_group_" not in sql
    assert params["now"] == datetime(2026, 7, 6, 9, 0)
    assert params["limit"] == 1


def test_mysql_article_account_config_repo_disables_account_config() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAccountConfigRepo(engine)

    repo.disable_account("行业观察")

    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_public_account_config" in sql
    assert "enabled = 0" in sql
    assert "wechat_group_config" not in sql
    assert params["account_name"] == "行业观察"


def test_mysql_article_account_config_repo_normalizes_time_fields() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 60,
                "daily_window_start": "7:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": None,
            }
        ]
    )
    repo = MysqlArticleAccountConfigRepo(engine)

    accounts = repo.list_accounts()

    assert accounts[0].daily_window_start == "07:30:00"
    assert accounts[0].daily_window_end == "19:30:00"


def test_mysql_article_account_config_repo_gets_account_by_stable_id() -> None:
    engine = FakeEngine(
        rows=[
            {
                "id": 9,
                "account_name": "行业观察",
                "account_type": "subscription",
                "enabled": 1,
                "priority": 2,
                "poll_interval_minutes": 60,
                "daily_window_start": "07:30:00",
                "daily_window_end": "19:30:00",
                "max_articles_per_round": 5,
                "collect_today_only": 1,
                "dedup_key": "article_hash",
                "last_success_collect_time": None,
                "remark": None,
            }
        ]
    )

    record = MysqlArticleAccountConfigRepo(engine).get_account(9)

    assert record is not None and record.id == 9
    sql, params = engine.connection.executions[0]
    assert re.search(r"SELECT\s+id\s*,", sql)
    assert "WHERE id = :source_id" in sql
    assert params == {"source_id": 9}


def test_mysql_article_account_config_repo_updates_account_by_stable_id() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAccountConfigRepo(engine)

    affected = repo.update_account_config(
        9,
        account_name="新账号",
        account_type="official",
        feed_url="http://werss.local/feed/new.xml",
        source_type="rss",
        priority=3,
        poll_interval_minutes=10,
        request_timeout_seconds=30,
        daily_window_start="08:00",
        daily_window_end="20:00",
        max_articles_per_round=10,
        collect_today_only=False,
        remark="更新",
    )

    assert affected == 1
    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_public_account_config" in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql
    assert "WHERE id = :source_id" in sql
    assert params["source_id"] == 9
    assert params["account_name"] == "新账号"
    assert params["collect_today_only"] == 0


def test_mysql_article_account_config_repo_sets_enabled_and_deletes_disabled_by_id() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAccountConfigRepo(engine)

    assert repo.set_account_enabled(9, False) == 1
    assert repo.delete_account(9) == 1

    enable_sql, enable_params = engine.connection.executions[0]
    delete_sql, delete_params = engine.connection.executions[1]
    assert "WHERE id = :source_id" in enable_sql
    assert enable_params == {"source_id": 9, "enabled": 0}
    assert "DELETE FROM wechat_public_account_config" in delete_sql
    assert "WHERE id = :source_id" in delete_sql
    assert "enabled = 0" in delete_sql
    assert delete_params == {"source_id": 9}


def test_article_config_record_and_feed_state_support_rss_fields() -> None:
    record = ArticleAccountConfigRecord(
        account_name="示例公众号", account_type="subscription",
        feed_url="http://werss.local/feed/abc.xml", source_type="rss",
        priority=1, poll_interval_minutes=10, request_timeout_seconds=30,
        daily_window_start="07:30", daily_window_end="19:30",
        max_articles_per_round=30,
    )
    assert record.feed_url.endswith("abc.xml")
    assert record.request_timeout_seconds == 30

    engine = FakeEngine()
    MysqlArticleAccountConfigRepo(engine).update_feed_state(
        9, etag='"v1"', modified="Sat, 11 Jul 2026 01:00:00 GMT",
        success_time=datetime(2026, 7, 11, 9), error_code=None,
    )
    sql, params = engine.connection.executions[0]
    assert "last_feed_etag = :etag" in sql
    assert "COALESCE(:success_time, last_success_collect_time)" in sql
    assert params["source_id"] == 9
