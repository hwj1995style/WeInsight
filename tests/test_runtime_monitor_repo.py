from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import PipelineType, RunStatus
from app.services.runtime_monitor_service import EventListFilter, RunListFilter
from app.storage import runtime_monitor_repo


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 12, 30, tzinfo=ZONE)


def test_run_filter_sql_uses_fixed_conditions_and_bound_values() -> None:
    where, params = runtime_monitor_repo._run_filter_clause(
        RunListFilter(
            pipeline_type=PipelineType.ARTICLE,
            status=RunStatus.FAILED,
            run_date=date(2026, 7, 10),
            job_id=7,
            job_name="50%_蛋",
        ),
        NOW - timedelta(days=1),
    )

    assert "job.pipeline_type = :pipeline_type" in where
    assert "run.scheduled_at >= :visible_since" in where
    assert params["visible_since"] == datetime(2026, 7, 9, 12, 30)
    assert "run.status = :status" in where
    assert "run.scheduled_at >= :date_start" in where
    assert "run.job_id = :job_id" in where
    assert "job.job_name LIKE :job_name ESCAPE" in where
    assert "50%_蛋" not in where
    assert params["pipeline_type"] == "article"
    assert params["status"] == "failed"
    assert params["job_name"] == "%50\\%\\_蛋%"
    assert params["date_start"] == datetime(2026, 7, 10)
    assert params["date_end"] == datetime(2026, 7, 11)


def test_event_filter_sql_uses_only_allowlisted_bound_conditions() -> None:
    where, params = runtime_monitor_repo._event_filter_clause(
        EventListFilter(
            job_id=7,
            run_id=11,
            target_run_id=13,
            pipeline_type=PipelineType.GROUP,
            level="error",
            start_at=NOW - timedelta(hours=1),
            end_at=NOW,
        ),
        NOW - timedelta(days=1),
    )

    for condition in (
        "event.job_id = :job_id",
        "event.run_id = :run_id",
        "event.target_run_id = :target_run_id",
        "job.pipeline_type = :pipeline_type",
        "event.level = :level",
        "event.create_time >= :start_at",
        "event.create_time <= :end_at",
        "event.create_time >= :visible_since",
    ):
        assert condition in where
    assert params["pipeline_type"] == "group"
    assert params["level"] == "error"
    assert params["start_at"] == datetime(2026, 7, 10, 11, 30)
    assert params["visible_since"] == datetime(2026, 7, 9, 12, 30)


def test_list_sql_applies_visibility_to_count_and_data_before_pagination() -> None:
    executed = []

    class Result:
        def scalar_one(self):
            return 0

        def mappings(self):
            return self

        def all(self):
            return []

    class Connection:
        def execute(self, statement, params=None):
            executed.append((" ".join(str(statement).split()), params))
            return Result()

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Context()

    repo = runtime_monitor_repo.MysqlRuntimeMonitorRepo(Engine())
    visible_since = datetime(2026, 4, 13, 12, 30, tzinfo=ZONE)
    repo.list_runs(RunListFilter(), 2, 20, visible_since)
    repo.list_events(EventListFilter(), 2, 50, visible_since)

    assert len(executed) == 4
    for sql, params in executed[:2]:
        assert "run.scheduled_at >= :visible_since" in sql
        assert params["visible_since"] == datetime(2026, 4, 13, 12, 30)
        if "ORDER BY" in sql:
            assert (
                sql.index("run.scheduled_at >= :visible_since")
                < sql.index("ORDER BY")
                < sql.index("LIMIT")
                < sql.index("OFFSET")
            )
    for sql, params in executed[2:]:
        assert "event.create_time >= :visible_since" in sql
        assert params["visible_since"] == datetime(2026, 4, 13, 12, 30)
        if "ORDER BY" in sql:
            assert (
                sql.index("event.create_time >= :visible_since")
                < sql.rindex("ORDER BY event.id DESC")
                < sql.index("LIMIT")
                < sql.index("OFFSET")
            )


def test_get_job_history_uses_mysql_datetime_floor_not_rolling_boundary() -> None:
    executed = []

    class Result:
        def scalar_one(self):
            return 0

        def mappings(self):
            return self

        def all(self):
            return []

    class Connection:
        def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return Result()

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Context()

    runtime_monitor_repo.MysqlRuntimeMonitorRepo(Engine()).get_job_history(7, 10)

    assert len(executed) == 4
    assert all(
        params["visible_since"] == datetime(1000, 1, 1)
        for _, params in executed
    )


def test_fill_trend_produces_24_shanghai_buckets_and_terminal_conservation() -> None:
    rows = [
        {"bucket_start": datetime(2026, 7, 10, 11), "status": "success", "count": 2},
        {
            "bucket_start": datetime(2026, 7, 10, 11),
            "status": "partial_success",
            "count": 1,
        },
        {"bucket_start": datetime(2026, 7, 10, 12), "status": "failed", "count": 3},
        {"bucket_start": datetime(2026, 7, 10, 12), "status": "aborted", "count": 1},
        {"bucket_start": datetime(2026, 7, 10, 12), "status": "cancelled", "count": 2},
        {"bucket_start": datetime(2026, 7, 10, 12), "status": "running", "count": 99},
        {"bucket_start": datetime(2026, 7, 10, 12), "status": "unknown", "count": 99},
    ]

    buckets = runtime_monitor_repo._fill_trend(rows, NOW)

    assert len(buckets) == 24
    assert buckets[0].bucket_start == datetime(
        2026, 7, 9, 13, tzinfo=ZONE
    )
    assert buckets[-1].bucket_start == datetime(
        2026, 7, 10, 12, tzinfo=ZONE
    )
    assert buckets[-2].successful_count == 3
    assert buckets[-1].unsuccessful_count == 4
    assert buckets[-1].cancelled_count == 2
    assert buckets[-1].terminal_total == 6


def test_dashboard_trend_sql_excludes_nonterminal_statuses() -> None:
    sql = str(runtime_monitor_repo._TREND_RUNS).lower()
    normalized = " ".join(sql.split())

    assert "status in (" in normalized
    for status in (
        "'success'",
        "'partial_success'",
        "'failed'",
        "'cancelled'",
        "'aborted'",
    ):
        assert status in normalized
    assert "running" not in sql
    assert "queued" not in sql
    assert "end_time >= :trend_start" in sql


def test_worker_expiry_boundary_is_fail_closed() -> None:
    worker = runtime_monitor_repo._worker_view(
        {
            "worker_id": "collector-1",
            "worker_type": "collector",
            "hostname": "HOST-A",
            "process_id": 123,
            "version": "v1",
            "status": "running",
            "last_heartbeat_at": datetime(2026, 7, 10, 12, 0),
            "start_time": datetime(2026, 7, 10, 11, 0),
            "last_error_summary": None,
            "within_ttl": 0,
        }
    )
    assert worker.is_live is False


def test_worker_query_prioritizes_live_and_recent_heartbeats() -> None:
    sql = " ".join(str(runtime_monitor_repo._WORKERS).split())

    assert (
        "ORDER BY within_ttl DESC, last_heartbeat_at DESC, "
        "worker_type ASC, hostname ASC, worker_id ASC"
    ) in sql


def test_event_query_aggregates_run_targets_without_duplicating_events() -> None:
    executed: list[str] = []

    class Result:
        def scalar_one(self):
            return 0

        def mappings(self):
            return self

        def all(self):
            return []

    class Connection:
        def execute(self, statement, params=None):
            executed.append(" ".join(str(statement).split()))
            return Result()

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Context()

    runtime_monitor_repo.MysqlRuntimeMonitorRepo(Engine()).list_events(
        EventListFilter(), 1, 50, NOW - timedelta(days=1)
    )

    data_sql = executed[1]
    assert "GROUP BY run_target.run_id" in data_sql
    assert "run_targets.run_id = event.run_id" in data_sql
    assert "COALESCE(run_targets.target_count, 0) AS target_count" in data_sql
    assert "run_targets.target_names_json" in data_sql


def test_runtime_event_decodes_ordered_target_names_safely() -> None:
    row = {
        "id": 1,
        "job_id": 10,
        "run_id": 757,
        "target_run_id": None,
        "pipeline_type": "article",
        "subject_name": None,
        "target_count": 2,
        "target_names_json": '["公众号A","公众号, B"]',
        "worker_id": "collector-1",
        "level": "warning",
        "event_type": "misfire",
        "stage": None,
        "message": "safe",
        "metrics_json": "{}",
        "actor_type": "worker",
        "actor_name": "collector-1",
        "create_time": datetime(2026, 7, 10, 12, 0),
    }

    event = runtime_monitor_repo._runtime_event(row)

    assert event.target_count == 2
    assert event.target_names == ("公众号A", "公众号, B")


def test_web_runtime_monitor_has_no_direct_ui_lock_dependency() -> None:
    source = Path("app/storage/runtime_monitor_repo.py").read_text(encoding="utf-8")

    assert "wechat_ui_lock" not in source
    assert "_UI_LOCK" not in source
    assert "_ui_lock_view" not in source


def test_worker_snapshot_uses_safe_unavailable_lock_state_without_query() -> None:
    executed: list[str] = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Connection:
        def execute(self, statement, params=None):
            sql = str(statement)
            executed.append(sql)
            assert "wechat_ui_lock" not in sql
            return Result()

    class BeginContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    class Engine:
        def begin(self):
            return BeginContext()

    repo = runtime_monitor_repo.MysqlRuntimeMonitorRepo(Engine())

    snapshot = repo.get_worker_snapshot(NOW, heartbeat_ttl_seconds=30)

    assert len(executed) == 2
    assert snapshot.workers == ()
    assert snapshot.health_checks == ()
    assert snapshot.ui_lock.state == "unavailable"


def test_latest_health_window_alias_avoids_mysql_reserved_function_name() -> None:
    sql = " ".join(str(runtime_monitor_repo._LATEST_HEALTH).lower().split())

    assert "as row_rank" in sql
    assert "ranked.row_rank = 1" in sql
    assert "as row_number" not in sql


def test_run_targets_rss_metrics_join_selects_one_latest_log_for_same_account() -> None:
    sql = " ".join(str(runtime_monitor_repo._RUN_TARGETS).lower().split())

    assert "article_log.id = ( select max(latest_log.id)" in sql
    assert "latest_log.batch_id = target_run.batch_id" in sql
    assert "latest_log.account_name = target.target_name_snapshot" in sql
    assert "article_log.batch_id = target_run.batch_id" not in sql


def test_event_metrics_summary_preserves_keys_and_sanitizes_string_values() -> None:
    summary = runtime_monitor_repo._safe_metrics(
        '{"failed":1,"detail":"<b>secret</b> https://example.com/raw"}'
    )

    assert '"failed":1' in summary
    assert "<b>" not in summary
    assert "https://" not in summary
