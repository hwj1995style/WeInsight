from __future__ import annotations

import sys

import pytest

import app.main as main_module
from app.main import main
from app.storage.article_runtime_metrics_repo import (
    ArticleRuntimeMetrics,
    ArticleTaskBacklogSummary,
    MysqlArticleRuntimeMetricsRepo,
)


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FROM wechat_public_account_config" in sql:
            return FakeResult(rows=[{"account_total_count": 20, "account_enabled_count": 3}])
        if "FROM wechat_article_collect_log" in sql and "collect_success_count" in sql:
            return FakeResult(
                rows=[
                    {
                        "collect_success_count": 7,
                        "collect_failed_count": 2,
                        "collect_skipped_count": 3,
                        "collect_total_count": 12,
                    }
                ]
            )
        if "FROM wechat_article_process_task" in sql:
            return FakeResult(
                rows=[
                    {"task_type": "clean_article", "status": "pending", "cnt": 4},
                    {"task_type": "analyze_article", "status": "failed", "cnt": 1},
                ]
            )
        if "latest_error_summary" in sql:
            return FakeResult(
                rows=[
                    {
                        "latest_error_summary": "WECHAT_ARTICLE_RPA_ERROR: copy timeout",
                    }
                ]
            )
        return FakeResult(rows=[{}])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_article_runtime_metrics_repo_returns_windowed_counts_and_backlogs() -> None:
    engine = FakeEngine()
    repo = MysqlArticleRuntimeMetricsRepo(engine)

    metrics = repo.get_metrics(hours=24)

    assert metrics.window_hours == 24
    assert metrics.account_total_count == 20
    assert metrics.account_enabled_count == 3
    assert metrics.collect_success_count == 7
    assert metrics.collect_failed_count == 2
    assert metrics.collect_skipped_count == 3
    assert metrics.collect_total_count == 12
    assert metrics.latest_error_summary == "WECHAT_ARTICLE_RPA_ERROR: copy timeout"
    assert metrics.task_backlogs[0].task_type == "clean_article"
    assert metrics.task_backlogs[0].status == "pending"
    assert metrics.task_backlogs[0].count == 4
    assert metrics.task_backlogs[1].task_type == "analyze_article"
    assert metrics.task_backlogs[1].status == "failed"
    assert metrics.task_backlogs[1].count == 1
    assert engine.connection.executions[1][1]["hours"] == 24
    assert engine.connection.executions[3][1]["hours"] == 24
    for sql, _params in engine.connection.executions:
        _assert_article_metrics_sql_is_safe(sql)
    task_sql = engine.connection.executions[2][0]
    assert "task_type <> 'article_daily_report'" in task_sql


def test_mysql_article_runtime_metrics_repo_rejects_non_positive_hours() -> None:
    repo = MysqlArticleRuntimeMetricsRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.get_metrics(hours=0)


def test_main_article_runtime_metrics_outputs_safe_counts(monkeypatch, capsys) -> None:
    class FakeRepo:
        def get_metrics(self, hours: int):
            assert hours == 6
            return ArticleRuntimeMetrics(
                window_hours=6,
                account_total_count=20,
                account_enabled_count=3,
                collect_success_count=7,
                collect_failed_count=2,
                collect_skipped_count=3,
                collect_total_count=12,
                latest_error_summary="WECHAT_ARTICLE_RPA_ERROR: copy timeout",
                task_backlogs=[
                    ArticleTaskBacklogSummary(task_type="clean_article", status="pending", count=4),
                    ArticleTaskBacklogSummary(task_type="analyze_article", status="failed", count=1),
                ],
            )

    monkeypatch.setattr(main_module, "build_real_article_runtime_metrics_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-runtime-metrics",
            "--config",
            "config/config.dev.yaml",
            "--hours",
            "6",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert (
        "article_runtime_metrics window_hours=6 account_total_count=20 account_enabled_count=3 "
        "collect_success_count=7 collect_failed_count=2 collect_skipped_count=3 collect_total_count=12"
    ) in output
    assert "latest_error_summary=WECHAT_ARTICLE_RPA_ERROR: copy timeout" in output
    assert "article_task_backlog task_type=clean_article status=pending count=4" in output
    assert "article_task_backlog task_type=analyze_article status=failed count=1" in output
    assert "mp.weixin.qq.com" not in output
    assert "article_url" not in output
    assert "article_body" not in output
    assert "body_text" not in output
    assert "html_content" not in output


def _assert_article_metrics_sql_is_safe(sql: str) -> None:
    assert "wechat_group_" not in sql
    assert "wechat_article_raw" not in sql
    assert "wechat_article_clean" not in sql
    assert "article_url" not in sql
    assert "article_content" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
