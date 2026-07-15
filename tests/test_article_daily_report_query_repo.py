from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.report_lifecycle import GenerationTrigger, ReportStatus
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
    def __init__(
        self,
        report_status: str = "final",
        generation_trigger: str = "compensation",
        last_generated_by: object = "system",
    ) -> None:
        self.executions: list[tuple[str, object]] = []
        self.report_status = report_status
        self.generation_trigger = generation_trigger
        self.last_generated_by = last_generated_by

    def _lifecycle(self) -> dict[str, object]:
        return {
            "report_status": self.report_status,
            "data_cutoff_time": datetime(2026, 7, 7, 0, 10),
            "generation_trigger": self.generation_trigger,
            "last_generated_by": self.last_generated_by,
        }

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
                        **self._lifecycle(),
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
                    **self._lifecycle(),
                }
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(
        self,
        report_status: str = "final",
        generation_trigger: str = "compensation",
        last_generated_by: object = "system",
    ) -> None:
        self.connection = FakeConnection(report_status, generation_trigger, last_generated_by)

    def begin(self):
        return self.connection


def test_mysql_article_daily_report_query_repo_lists_report_summaries_without_body_fields() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportQueryRepo(engine)

    reports = repo.list_daily_reports(report_date=date(2026, 7, 6), account_name=None, limit=10)

    assert len(reports) == 1
    assert reports[0].article_count == 2
    assert reports[0].report_status is ReportStatus.FINAL
    assert reports[0].data_cutoff_time == datetime(
        2026, 7, 7, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_daily_report" in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "wechat_group_" not in sql
    assert "markdown_body" not in sql
    for column in ("report_status", "data_cutoff_time", "generation_trigger", "last_generated_by"):
        assert column in sql
    _assert_article_daily_report_query_sql_is_isolated(sql)
    assert params["report_date"] == date(2026, 7, 6)
    assert params["limit"] == 10


def test_mysql_article_daily_report_query_repo_gets_single_report_detail() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportQueryRepo(engine)

    report = repo.get_daily_report(report_date=date(2026, 7, 6), account_name="行业观察")

    assert report is not None
    assert report.markdown_body.startswith("# 行业观察")
    assert report.generation_trigger is GenerationTrigger.COMPENSATION
    assert report.last_generated_by == "system"
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_daily_report" in sql
    assert "markdown_body" in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "wechat_group_" not in sql
    _assert_article_daily_report_query_sql_is_isolated(sql)
    assert params["account_name"] == "行业观察"


@pytest.mark.parametrize(
    ("report_status", "generation_trigger", "last_generated_by", "error_field"),
    [
        ("corrupt", "manual", "admin", "report_status"),
        ("final", "corrupt", "admin", "generation_trigger"),
        ("provisional", "automatic", "admin", "provisional"),
        ("final", "manual", "   ", "generated_by"),
        ("final", "manual", None, "generated_by"),
    ],
)
def test_mysql_article_daily_report_query_repo_rejects_invalid_lifecycle_values(
    report_status: str,
    generation_trigger: str,
    last_generated_by: object,
    error_field: str,
) -> None:
    repo = MysqlArticleDailyReportQueryRepo(
        FakeEngine(report_status, generation_trigger, last_generated_by)
    )

    with pytest.raises(ValueError, match=error_field):
        repo.list_daily_reports(report_date=date(2026, 7, 6), account_name=None, limit=10)


def _assert_article_daily_report_query_sql_is_isolated(sql: str) -> None:
    assert "article_url" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
    assert "ocr_raw" not in sql
