from __future__ import annotations

import pytest

from app.storage.group_runtime_metrics_repo import MysqlGroupRuntimeMetricsRepo


class FakeResult:
    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "FROM wechat_group_collect_log" in sql:
            return FakeResult(
                rows=[
                    {
                        "collect_success_count": 6,
                        "collect_failed_count": 2,
                    }
                ]
            )
        if "FROM wechat_group_process_task" in sql:
            return FakeResult(
                rows=[
                    {"task_type": "clean_group_msg", "status": "pending", "cnt": 3},
                    {"task_type": "analyze_group_msg", "status": "failed", "cnt": 1},
                ]
            )
        if "FROM wechat_group_daily_report" in sql:
            return FakeResult(rows=[{"daily_report_count": 4}])
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


def test_mysql_group_runtime_metrics_repo_returns_windowed_metrics_and_backlogs() -> None:
    engine = FakeEngine()
    repo = MysqlGroupRuntimeMetricsRepo(engine)

    metrics = repo.get_metrics(hours=24)

    assert metrics.window_hours == 24
    assert metrics.collect_success_count == 6
    assert metrics.collect_failed_count == 2
    assert metrics.collect_total_count == 8
    assert metrics.collect_failure_rate == 0.25
    assert metrics.daily_report_count == 4
    assert metrics.task_backlogs[0].task_type == "clean_group_msg"
    assert metrics.task_backlogs[0].status == "pending"
    assert metrics.task_backlogs[0].count == 3
    assert metrics.task_backlogs[1].task_type == "analyze_group_msg"
    assert metrics.task_backlogs[1].status == "failed"
    assert metrics.task_backlogs[1].count == 1
    assert engine.connection.executions[0][1]["hours"] == 24
    assert engine.connection.executions[2][1]["hours"] == 24
    for sql, params in engine.connection.executions:
        _assert_runtime_metrics_sql_is_safe(sql)


def test_mysql_group_runtime_metrics_repo_returns_zero_rate_when_no_collects() -> None:
    class EmptyCollectConnection(FakeConnection):
        def execute(self, statement, params=None):
            sql = str(statement)
            self.executions.append((sql, params))
            if "FROM wechat_group_collect_log" in sql:
                return FakeResult(rows=[{"collect_success_count": 0, "collect_failed_count": 0}])
            if "FROM wechat_group_process_task" in sql:
                return FakeResult(rows=[])
            if "FROM wechat_group_daily_report" in sql:
                return FakeResult(rows=[{"daily_report_count": 0}])
            return FakeResult(rows=[{}])

    class EmptyCollectEngine:
        def __init__(self) -> None:
            self.connection = EmptyCollectConnection()

        def begin(self):
            return self.connection

    repo = MysqlGroupRuntimeMetricsRepo(EmptyCollectEngine())

    metrics = repo.get_metrics(hours=1)

    assert metrics.collect_total_count == 0
    assert metrics.collect_failure_rate == 0.0


def test_mysql_group_runtime_metrics_repo_rejects_non_positive_hours() -> None:
    repo = MysqlGroupRuntimeMetricsRepo(FakeEngine())

    with pytest.raises(ValueError):
        repo.get_metrics(hours=0)


def _assert_runtime_metrics_sql_is_safe(sql: str) -> None:
    assert "wechat_article_process_task" not in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_msg_clean" not in sql
    assert "wechat_group_msg_analysis" not in sql
    assert "msg_content" not in sql
    assert "raw_content" not in sql
    assert "clean_content" not in sql
    assert "markdown_body" not in sql
