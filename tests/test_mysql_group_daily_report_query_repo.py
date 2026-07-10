from __future__ import annotations

from datetime import date, datetime

from app.storage.group_daily_report_query_repo import MysqlGroupDailyReportQueryRepo


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
                        "report_date": date(2026, 7, 3),
                        "group_name": "核心群A",
                        "title": "核心群A 2026-07-03 群日报草稿",
                        "markdown_body": "# 核心群A 2026-07-03 群日报草稿",
                        "message_count": 14,
                        "sender_count": 7,
                        "demand_count": 0,
                        "supply_count": 1,
                        "contact_count": 0,
                        "peak_hour": 10,
                        "top_keywords": "[]",
                        "report_version": "v1",
                        "generate_time": datetime(2026, 7, 3, 18, 0, 0),
                    }
                ]
            )
        return FakeResult(
            rows=[
                {
                    "report_date": date(2026, 7, 3),
                    "group_name": "核心群A",
                    "title": "核心群A 2026-07-03 群日报草稿",
                    "message_count": 14,
                    "sender_count": 7,
                    "demand_count": 0,
                    "supply_count": 1,
                    "contact_count": 0,
                    "peak_hour": 10,
                    "generate_time": datetime(2026, 7, 3, 18, 0, 0),
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


def test_mysql_group_daily_report_query_repo_lists_report_summaries_without_raw_or_clean_tables() -> None:
    engine = FakeEngine()
    repo = MysqlGroupDailyReportQueryRepo(engine)

    reports = repo.list_daily_reports(report_date=date(2026, 7, 3), group_name=None, limit=10)

    assert len(reports) == 1
    assert reports[0].message_count == 14
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_group_daily_report" in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "markdown_body" not in sql
    assert params["report_date"] == date(2026, 7, 3)
    assert params["limit"] == 10


def test_mysql_group_daily_report_query_repo_gets_single_report_detail() -> None:
    engine = FakeEngine()
    repo = MysqlGroupDailyReportQueryRepo(engine)

    report = repo.get_daily_report(report_date=date(2026, 7, 3), group_name="核心群A")

    assert report is not None
    assert report.markdown_body.startswith("# 核心群A")
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_group_daily_report" in sql
    assert "markdown_body" in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert params["group_name"] == "核心群A"
