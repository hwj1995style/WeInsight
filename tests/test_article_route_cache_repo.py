from __future__ import annotations

from datetime import datetime

from app.storage.article_route_cache_repo import MysqlArticleRouteCacheRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.executions: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params or {}))
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


def test_get_active_route_reads_only_article_route_cache() -> None:
    engine = FakeEngine(
        [
            {
                "account_name": "一箱蛋",
                "route_type": "bottom_menu",
                "entry_label": "蛋价资讯",
                "entry_index": None,
                "link_extract_type": "copy_link_menu",
                "cache_status": "active",
                "failure_count": 0,
                "last_error_code": None,
                "last_error_msg": None,
            }
        ]
    )
    repo = MysqlArticleRouteCacheRepo(engine)

    record = repo.get_active_route("一箱蛋")

    assert record is not None
    assert record.account_name == "一箱蛋"
    assert record.route_type == "bottom_menu"
    assert record.entry_label == "蛋价资讯"
    assert record.link_extract_type == "copy_link_menu"
    sql = engine.connection.executions[0][0]
    assert "FROM wechat_article_route_cache" in sql
    assert "wechat_group_" not in sql


def test_upsert_success_resets_failure_count() -> None:
    engine = FakeEngine()
    repo = MysqlArticleRouteCacheRepo(engine)
    now = datetime(2026, 7, 7, 10, 0, 0)

    repo.upsert_success(
        account_name="一箱蛋",
        route_type="bottom_menu",
        link_extract_type="copy_link_menu",
        entry_label="蛋价资讯",
        entry_index=None,
        success_time=now,
    )

    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_article_route_cache" in sql
    assert "failure_count = 0" in sql
    assert params["account_name"] == "一箱蛋"
    assert params["route_type"] == "bottom_menu"
    assert params["link_extract_type"] == "copy_link_menu"


def test_mark_failure_invalidates_after_threshold() -> None:
    engine = FakeEngine()
    repo = MysqlArticleRouteCacheRepo(engine)
    now = datetime(2026, 7, 7, 10, 0, 0)

    repo.mark_failure(
        account_name="一箱蛋",
        error_code="COPY_LINK_FAILED",
        error_msg="menu item not found",
        failure_time=now,
        failure_threshold=3,
    )

    sql, params = engine.connection.executions[0]
    assert "UPDATE wechat_article_route_cache" in sql
    assert "cache_status = CASE" in sql
    assert params["failure_threshold"] == 3
    assert params["error_code"] == "COPY_LINK_FAILED"


def test_mark_failure_sanitizes_url_like_error_messages() -> None:
    engine = FakeEngine()
    repo = MysqlArticleRouteCacheRepo(engine)
    now = datetime(2026, 7, 7, 10, 0, 0)

    repo.mark_failure(
        account_name="一箱蛋",
        error_code="COPY_LINK_FAILED",
        error_msg="menu https://mp.weixin.qq.com/s/abc has issue",
        failure_time=now,
        failure_threshold=3,
    )

    _, params = engine.connection.executions[0]
    assert params["error_msg"] == "menu [redacted-url] has issue"
