from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain.article_daily_report import ArticleDailyReportDraft
from app.domain.report_lifecycle import GenerationTrigger, ReportLifecycle
from app.storage.article_daily_report_repo import MysqlArticleDailyReportRepo


INIT_SQL = Path("sql/init.sql")
MIGRATION = Path("sql/migrations/20260706_004_create_article_daily_report.sql")


def test_init_sql_has_article_daily_report_table() -> None:
    sql = INIT_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_daily_report" in sql
    for column in [
        "report_date DATE NOT NULL COMMENT '日报日期'",
        "account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称'",
        "title VARCHAR(300) NOT NULL COMMENT '日报标题'",
        "markdown_body MEDIUMTEXT NOT NULL COMMENT 'Markdown日报草稿'",
        "article_count INT DEFAULT 0 COMMENT '文章数'",
        "avg_content_length INT DEFAULT 0 COMMENT '平均正文长度'",
        "top_tags_json TEXT NULL COMMENT '主题标签TOP JSON'",
        "top_keywords_json TEXT NULL COMMENT '关键词TOP JSON'",
        "report_version VARCHAR(20) DEFAULT 'v1' COMMENT '日报模板版本'",
        "generate_time DATETIME NOT NULL COMMENT '生成时间'",
    ]:
        assert column in sql
    assert "UNIQUE KEY uk_article_daily_report (report_date, account_name)" in sql
    assert "KEY idx_article_daily_report_date (report_date)" in sql
    assert "KEY idx_article_daily_report_generate_time (generate_time)" in sql


def test_article_daily_report_migration_is_idempotent_and_isolated() -> None:
    assert MIGRATION.exists()

    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_daily_report" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()


def test_mysql_article_daily_report_repo_builds_stats_from_article_analysis_only() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportRepo(engine)

    stats = repo.list_daily_report_stats(report_date=date(2026, 7, 6), account_name="行业观察")

    assert len(stats) == 1
    assert stats[0].account_name == "行业观察"
    assert stats[0].article_count == 2
    assert stats[0].avg_content_length == 1300
    assert stats[0].top_tags == [("深圳", 2), ("报价", 1), ("湖北", 1)]
    assert stats[0].top_keywords == [("供应链", 2), ("市场", 1)]
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_analysis" in sql
    assert "COALESCE(quote_date, publish_date) = :report_date" in sql
    assert "wechat_article_process_task" not in sql
    assert "wechat_article_clean" not in sql
    _assert_article_daily_report_sql_is_isolated(sql)
    assert params["report_date"] == date(2026, 7, 6)
    assert params["account_name"] == "行业观察"


def test_mysql_article_daily_report_repo_upserts_report_and_marks_article_task_success() -> None:
    engine = FakeEngine()
    repo = MysqlArticleDailyReportRepo(engine)
    report = ArticleDailyReportDraft(
        report_date=date(2026, 7, 6),
        account_name="行业观察",
        title="行业观察 2026-07-06 文章日报草稿",
        markdown_body="# 行业观察 2026-07-06 文章日报草稿",
        article_count=2,
        avg_content_length=1300,
        top_tags=[("深圳", 2), ("报价", 1)],
        top_keywords=[("供应链", 1)],
        report_version="v1",
        generate_time=datetime(2026, 7, 6, 20, 0),
    )

    lifecycle = ReportLifecycle.final(
        cutoff=datetime(2026, 7, 7, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        trigger=GenerationTrigger.COMPENSATION,
        generated_by="system",
    )
    repo.upsert_daily_report(report, lifecycle)
    repo.mark_daily_report_task_success(date(2026, 7, 6))

    report_sql, report_params = engine.connection.executions[0]
    success_sql, success_params = engine.connection.executions[1]
    assert "INSERT INTO wechat_article_daily_report" in report_sql
    assert "ON DUPLICATE KEY UPDATE" in report_sql
    assert json.loads(report_params["top_tags_json"])[0] == {"tag": "深圳", "count": 2}
    for column in (
        "report_status",
        "data_cutoff_time",
        "generation_trigger",
        "last_generated_by",
    ):
        assert column in report_sql
        assert f"{column} = VALUES({column})" in report_sql
    assert report_params["report_status"] == "final"
    assert report_params["data_cutoff_time"] == datetime(2026, 7, 7, 0, 10)
    assert report_params["data_cutoff_time"].tzinfo is None
    assert report_params["generation_trigger"] == "compensation"
    assert report_params["last_generated_by"] == "system"
    assert "status = 'success'" in success_sql
    assert "task_type = 'article_daily_report'" in success_sql
    assert success_params["ref_id"] == "2026-07-06"
    _assert_article_daily_report_sql_is_isolated(report_sql + success_sql)


class FakeResult:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

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
        if "FROM wechat_article_analysis" in sql:
            return FakeResult(
                rows=[
                    {
                        "account_name": "行业观察",
                        "content_length": 1200,
                        "topic_tags_json": '["深圳", "报价"]',
                        "keyword_hits_json": '["供应链"]',
                    },
                    {
                        "account_name": "行业观察",
                        "content_length": 1400,
                        "topic_tags_json": '["深圳", "湖北"]',
                        "keyword_hits_json": '["供应链", "市场"]',
                    },
                ]
            )
        return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def _assert_article_daily_report_sql_is_isolated(sql: str) -> None:
    assert "wechat_group_" not in sql
    assert "article_url" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
    assert "ocr_raw" not in sql
