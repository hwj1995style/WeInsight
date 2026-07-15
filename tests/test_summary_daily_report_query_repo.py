from __future__ import annotations

from datetime import date, datetime

from app.storage.summary_daily_report_query_repo import MysqlSummaryDailyReportQueryRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FROM wechat_group_daily_report" in sql:
            return FakeResult(
                [
                    {
                        "report_date": date(2026, 7, 6),
                        "group_name": "核心群A",
                        "title": "核心群A 2026-07-06 群日报草稿",
                        "message_count": 14,
                        "sender_count": 7,
                        "demand_count": 1,
                        "supply_count": 2,
                        "contact_count": 0,
                        "peak_hour": 10,
                        "generate_time": datetime(2026, 7, 6, 18, 0),
                    }
                ]
            )
        return FakeResult(
            [
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


def test_mysql_summary_query_repo_reads_only_daily_report_tables() -> None:
    engine = FakeEngine()
    repo = MysqlSummaryDailyReportQueryRepo(engine)

    group_reports = repo.list_group_reports(report_date=date(2026, 7, 6))
    article_reports = repo.list_article_reports(report_date=date(2026, 7, 6))

    assert group_reports[0].group_name == "核心群A"
    assert group_reports[0].message_count == 14
    assert article_reports[0].account_name == "行业观察"
    assert article_reports[0].article_count == 2
    sql = "\n".join(statement for statement, _ in engine.connection.executions)
    assert "FROM wechat_group_daily_report" in sql
    assert "FROM wechat_article_daily_report" in sql
    assert "wechat_group_process_task" not in sql
    assert "wechat_article_process_task" not in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "wechat_article_clean" not in sql
    assert "wechat_group_msg_analysis" not in sql
    assert "wechat_article_analysis" not in sql
    assert "markdown_body" not in sql
    assert "article_url" not in sql
    assert engine.connection.executions[0][1]["report_date"] == date(2026, 7, 6)
    assert engine.connection.executions[1][1]["report_date"] == date(2026, 7, 6)
