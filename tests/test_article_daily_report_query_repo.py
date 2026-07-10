from __future__ import annotations

from datetime import date, datetime

from app.storage.article_daily_report_query_repo import MysqlArticleDailyReportQueryRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "markdown_body" in sql:
            return FakeResult(
                rows=[
                    {
                        "report_date": date(2026, 7, 6),
                        "account_name": "行业观察",
                        "title": "行业观察 2026-07-06 文章日报草稿",
                        "markdown_body": "# 行业观察 2026-07-06 文章日报草稿",
                        "article_count": 2,
                        "avg_content_length": 1300,
                        "top_tags_json": "[]",
                        "top_keywords_json": "[]",
                        "report_version": "v1",
                        "generate_time": datetime(2026, 7, 6, 20, 0),
                    }
                ]
            )
        return FakeResult(
            rows=[
                {
                    "report_date": date(2026, 7, 6),
                    "account_name": "行业观察",
                    "title": "行业观察 2026-07-06 文章日报草稿",
                    "article_count": 2,
                    "avg_content_length": 1300,
                    "generate_time": datetime(2026, 7, 6, 20, 0),
                }
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_article_daily_report_query_repo_lists_report_summaries_without_body_fields() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportQueryRepo(engine)

    reports = repo.list_daily_reports(report_date=date(2026, 7, 6), account_name=None, limit=10)

    assert len(reports) == 1
    assert reports[0].article_count == 2
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_daily_report" in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "wechat_group_" not in sql
    assert "markdown_body" not in sql
    _assert_article_daily_report_query_sql_is_isolated(sql)
    assert params["report_date"] == date(2026, 7, 6)
    assert params["limit"] == 10


def test_mysql_article_daily_report_query_repo_gets_single_report_detail() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportQueryRepo(engine)

    report = repo.get_daily_report(report_date=date(2026, 7, 6), account_name="行业观察")

    assert report is not None
    assert report.markdown_body.startswith("# 行业观察")
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_daily_report" in sql
    assert "markdown_body" in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "wechat_group_" not in sql
    _assert_article_daily_report_query_sql_is_isolated(sql)
    assert params["account_name"] == "行业观察"


def _assert_article_daily_report_query_sql_is_isolated(sql: str) -> None:
    assert "article_url" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
    assert "ocr_raw" not in sql
