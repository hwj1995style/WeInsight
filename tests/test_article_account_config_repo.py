from __future__ import annotations

from datetime import datetime

from app.storage.article_config_repo import ArticleAccountConfigRecord, MysqlArticleAccountConfigRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []
        self.rowcount = 1

    def mappings(self):
        return self

    def all(self):
        return self._rows


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


def test_mysql_article_account_config_repo_upserts_account_config() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAccountConfigRepo(engine)

    repo.upsert_account_config(
        account_name="行业观察",
        account_type="subscription",
        enabled=True,
        priority=2,
        poll_interval_minutes=60,
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


def test_mysql_article_account_config_repo_lists_accounts() -> None:
    last_success = datetime(2026, 7, 3, 8, 30)
    engine = FakeEngine(
        rows=[
            {
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
        )
    ]
    sql, _ = engine.connection.executions[0]
    assert "FROM wechat_public_account_config" in sql
    assert "ORDER BY priority ASC" in sql
    assert "wechat_group_config" not in sql


def test_mysql_article_account_config_repo_lists_due_accounts_from_article_config_only() -> None:
    engine = FakeEngine(
        rows=[
            {
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
                "remark": "授权账号",
            }
        ]
    )
    repo = MysqlArticleAccountConfigRepo(engine)

    accounts = repo.list_due_accounts(now=datetime(2026, 7, 6, 9, 0), limit=1)

    assert accounts[0].account_name == "行业观察"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_public_account_config" in sql
    assert "enabled = 1" in sql
    assert "TIME(:now)" in sql
    assert "TIMESTAMPDIFF(MINUTE" in sql
    assert "ORDER BY priority ASC" in sql
    assert "LIMIT :limit" in sql
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
