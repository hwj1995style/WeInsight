from __future__ import annotations

from datetime import datetime

from app.storage.group_runtime_summary_repo import MysqlGroupRuntimeSummaryRepo


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
        if "FROM wechat_group_config" in sql:
            return FakeResult(
                rows=[
                    {
                        "total_count": 2,
                        "enabled_count": 1,
                        "core_enabled_count": 1,
                    }
                ]
            )
        if "FROM wechat_group_process_task" in sql:
            return FakeResult(
                rows=[
                    {"task_type": "clean_group_msg", "status": "success", "cnt": 14},
                    {"task_type": "analyze_group_msg", "status": "success", "cnt": 14},
                    {"task_type": "group_daily_report", "status": "success", "cnt": 1},
                ]
            )
        if "FROM wechat_ui_lock" in sql:
            return FakeResult(rows=[])
        if "FROM wechat_group_collect_log" in sql:
            return FakeResult(
                rows=[
                    {
                        "source_name": "核心群A",
                        "batch_id": "batch-1",
                        "status": "success",
                        "start_time": datetime(2026, 7, 3, 10, 0, 0),
                        "end_time": datetime(2026, 7, 3, 10, 0, 5),
                        "read_count": 4,
                        "insert_count": 1,
                        "duplicate_count": 3,
                        "error_code": None,
                        "screenshot_path": None,
                    }
                ]
            )
        return FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_group_runtime_summary_repo_reads_safe_summary_tables_only() -> None:
    engine = FakeEngine()
    repo = MysqlGroupRuntimeSummaryRepo(engine)

    summary = repo.get_summary(limit=5)

    assert summary.config.total_count == 2
    assert summary.config.enabled_count == 1
    assert summary.config.core_enabled_count == 1
    assert summary.ui_lock.status == "free"
    assert summary.task_backlogs[0].task_type == "clean_group_msg"
    assert summary.latest_collect_logs[0].source_name == "核心群A"
    for sql, params in engine.connection.executions:
        assert "wechat_group_msg_raw" not in sql
        assert "wechat_group_msg_clean" not in sql
        assert "wechat_group_msg_analysis" not in sql
        assert "msg_content" not in sql
        assert "raw_content" not in sql
        assert "clean_content" not in sql
        assert "markdown_body" not in sql
    assert engine.connection.executions[-1][1]["limit"] == 5
