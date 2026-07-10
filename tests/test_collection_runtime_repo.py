from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.collection_jobs import PipelineType, RunStatus
import app.storage.collection_runtime_repo as runtime_module
from app.storage.collection_runtime_repo import (
    MysqlCollectionRuntimeRepo,
    RuntimeStateError,
    TargetRunOutcome,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 25, tzinfo=ZONE)


class Result:
    def __init__(
        self, *, rows=None, rowcount=1, lastrowid=None, scalar=None
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, results) -> None:
        self.connection = Connection(results)
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


def due_job(**changes):
    row = {
        "job_id": 7,
        "job_name": "晨间群采集",
        "pipeline_type": "group",
        "effective_start_at": datetime(2026, 7, 10, 9, 0),
        "effective_end_at": datetime(2026, 7, 10, 18, 0),
        "daily_window_start": time(9, 0),
        "daily_window_end": timedelta(hours=18),
        "interval_seconds": 600,
        "next_run_at": datetime(2026, 7, 10, 9, 0),
        "target_total_count": 2,
    }
    row.update(changes)
    return row


def targets():
    return [
        {
            "job_target_id": 101,
            "source_id": 11,
            "source_name": "甲群",
            "priority": 1,
            "config_snapshot_json": '{"backtrack_pages":4}',
        },
        {
            "job_target_id": 102,
            "source_id": 12,
            "source_name": "乙群",
            "priority": 2,
            "config_snapshot_json": '{"backtrack_pages":3}',
        },
    ]


def claim_engine(job=None, *, insert_rowcount=1, target_rows=None):
    return Engine(
        [
            Result(rows=[] if job is None else [job]),
            *(
                []
                if job is None
                else [
                    Result(rowcount=insert_rowcount, lastrowid=41),
                    *(
                        []
                        if insert_rowcount != 1
                        else [
                            Result(rows=target_rows or targets()),
                            Result(),
                            Result(),
                            Result(),
                        ]
                    ),
                ]
            ),
        ]
    )


def mysql_integrity_error(code: int, message: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(code, message))


def test_claim_prefers_group_uses_skip_locked_and_creates_owned_run() -> None:
    engine = claim_engine(due_job())

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        NOW, "collector-1", 120
    )

    assert claimed is not None
    assert claimed.run_id == 41
    assert claimed.pipeline_type is PipelineType.GROUP
    assert claimed.scheduled_at == datetime(2026, 7, 10, 9, 20, tzinfo=ZONE)
    assert claimed.status is RunStatus.RUNNING
    assert [target.source_id for target in claimed.targets] == [11, 12]
    assert engine.begin_count == 1
    select_sql, select_params = engine.connection.executions[0]
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert "CASE WHEN pipeline_type = 'group' THEN 0 ELSE 1 END" in select_sql
    assert "next_run_at ASC, id ASC" in select_sql
    assert "status IN ('scheduled', 'active')" in select_sql
    assert "NOT EXISTS" in select_sql
    assert select_params == {"now": datetime(2026, 7, 10, 9, 25)}
    insert_sql, insert_params = engine.connection.executions[1]
    assert "INSERT INTO" in insert_sql
    assert "INSERT IGNORE" not in insert_sql
    assert "uk_job_schedule" in insert_sql
    assert insert_params["worker_id"] == "collector-1"
    assert insert_params["lease_expires_at"] == datetime(2026, 7, 10, 9, 27)
    assert insert_params["scheduled_at"] == datetime(2026, 7, 10, 9, 20)


def test_claim_uses_persisted_target_snapshots_and_stable_order() -> None:
    engine = claim_engine(due_job())

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        NOW, "collector-1", 120
    )

    assert claimed is not None
    target_sql, target_params = engine.connection.executions[2]
    assert "wechat_collection_job_target" in target_sql
    assert "target_name_snapshot" in target_sql
    assert "config_snapshot_json" in target_sql
    assert "wechat_group_config" not in target_sql
    assert "wechat_public_account_config" not in target_sql
    assert "ORDER BY priority_snapshot ASC, target_name_snapshot ASC, id ASC" in target_sql
    assert target_params == {"job_id": 7}
    target_insert_sql, target_insert_params = engine.connection.executions[3]
    assert "wechat_collection_job_target_run" in target_insert_sql
    assert [item["job_target_id"] for item in target_insert_params] == [101, 102]
    assert claimed.targets[0].config_snapshot_json == '{"backtrack_pages":4}'


def test_claim_advances_fixed_grid_and_writes_misfire_count_in_same_transaction() -> None:
    engine = claim_engine(due_job())

    MysqlCollectionRuntimeRepo(engine).claim_next_due(NOW, "collector-1", 120)

    update_sql, update_params = engine.connection.executions[4]
    assert "next_run_at = :next_run_at" in update_sql
    assert "status = 'active'" in update_sql
    assert update_params["next_run_at"] == datetime(2026, 7, 10, 9, 30)
    event_sql, event_params = engine.connection.executions[5]
    assert "wechat_collection_job_event" in event_sql
    assert event_params["event_type"] == "misfire"
    assert event_params["metrics_json"] == '{"missed_count":2}'
    assert engine.begin_count == 1


def test_claim_marks_job_completed_when_no_later_grid_period_exists() -> None:
    final_now = datetime(2026, 7, 10, 9, 20, tzinfo=ZONE)
    job = due_job(
        effective_end_at=datetime(2026, 7, 10, 9, 21),
        next_run_at=datetime(2026, 7, 10, 9, 20),
        target_total_count=1,
    )
    engine = claim_engine(job, target_rows=targets()[:1])

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        final_now, "collector-1", 120
    )

    assert claimed is not None
    update_sql, params = engine.connection.executions[4]
    assert "status = 'completed'" in update_sql
    assert "next_run_at = NULL" in update_sql
    assert params == {"job_id": 7}


def test_duplicate_schedule_is_not_claimed_or_mistaken_for_owned_run() -> None:
    engine = Engine(
        [
            Result(rows=[due_job()]),
            mysql_integrity_error(
                1062,
                "Duplicate entry '7-2026-07-10 09:20:00' for key "
                "'wechat_collection_job_run.uk_job_schedule'",
            ),
        ]
    )

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        NOW, "collector-2", 120
    )

    assert claimed is None
    assert engine.begin_count == 1
    assert len(engine.connection.executions) == 2
    assert "INSERT INTO" in engine.connection.executions[1][0]
    assert "INSERT IGNORE" not in engine.connection.executions[1][0]


def test_claim_propagates_non_schedule_integrity_errors() -> None:
    engine = Engine(
        [
            Result(rows=[due_job()]),
            mysql_integrity_error(
                1452,
                "Cannot add or update child row: foreign key constraint fails",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        MysqlCollectionRuntimeRepo(engine).claim_next_due(
            NOW, "collector-1", 120
        )


def test_claim_does_not_swallow_other_duplicate_constraints() -> None:
    engine = Engine(
        [
            Result(rows=[due_job()]),
            mysql_integrity_error(
                1062,
                "Duplicate entry 'x' for key 'some_other_unique_key'",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        MysqlCollectionRuntimeRepo(engine).claim_next_due(
            NOW, "collector-1", 120
        )


def test_claim_returns_none_when_nothing_is_due() -> None:
    engine = claim_engine()
    assert (
        MysqlCollectionRuntimeRepo(engine).claim_next_due(
            NOW, "collector-1", 120
        )
        is None
    )
    assert len(engine.connection.executions) == 1


def test_claim_outside_window_advances_without_starting_rpa() -> None:
    now = datetime(2026, 7, 10, 20, 0, tzinfo=ZONE)
    engine = Engine(
        [
            Result(
                rows=[
                    due_job(
                        effective_end_at=datetime(2026, 7, 12, 18, 0)
                    )
                ]
            ),
            Result(),
        ]
    )

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        now, "collector-1", 120
    )

    assert claimed is None
    assert len(engine.connection.executions) == 2
    assert "INSERT" not in engine.connection.executions[1][0]
    assert engine.connection.executions[1][1]["next_run_at"] == datetime(
        2026, 7, 11, 9, 0
    )


def test_year_long_misfire_count_is_day_bounded_not_period_bounded(
    monkeypatch,
) -> None:
    first_due = datetime(2025, 7, 10, 9, 0)
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZONE)
    engine = claim_engine(
        due_job(
            effective_start_at=first_due,
            effective_end_at=datetime(2026, 7, 12, 18, 0),
            interval_seconds=30,
            next_run_at=first_due,
        )
    )
    real_next_run_at = runtime_module.next_run_at
    calls = 0

    def counted_next_run_at(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_next_run_at(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "next_run_at", counted_next_run_at)

    claimed = MysqlCollectionRuntimeRepo(engine).claim_next_due(
        now, "collector-1", 120
    )

    assert claimed is not None
    assert calls == 1
    assert engine.connection.executions[5][1]["metrics_json"] == (
        '{"missed_count":394200}'
    )


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"now": datetime(2026, 7, 10, 9, 0)}, "now"),
        ({"now": datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)}, "Asia/Shanghai"),
        ({"worker_id": ""}, "worker_id"),
        ({"lease_seconds": True}, "lease_seconds"),
        ({"lease_seconds": 0}, "lease_seconds"),
    ],
)
def test_claim_rejects_invalid_identity_time_and_lease(kwargs, error) -> None:
    values = {"now": NOW, "worker_id": "collector-1", "lease_seconds": 120}
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError), match=error):
        MysqlCollectionRuntimeRepo(Engine([])).claim_next_due(**values)


def test_heartbeat_refreshes_only_owned_running_run_and_returns_exact_bool() -> None:
    engine = Engine([Result(rowcount=1)])
    repo = MysqlCollectionRuntimeRepo(engine)

    assert repo.heartbeat_run(41, "collector-1", NOW, 120) is True

    sql, params = engine.connection.executions[0]
    assert "id = :run_id" in sql
    assert "worker_id = :worker_id" in sql
    assert "status = 'running'" in sql
    assert params["lease_expires_at"] == datetime(2026, 7, 10, 9, 27)

    missed = MysqlCollectionRuntimeRepo(Engine([Result(rowcount=0)]))
    assert missed.heartbeat_run(41, "collector-2", NOW, 120) is False


def test_stop_requested_uses_bound_exists_query() -> None:
    engine = Engine([Result(scalar=True)])
    assert MysqlCollectionRuntimeRepo(engine).is_stop_requested(7) is True
    sql, params = engine.connection.executions[0]
    assert "SELECT EXISTS" in sql
    assert "status = 'stop_requested'" in sql
    assert params == {"job_id": 7}


def test_start_target_updates_only_queued_target_of_running_run() -> None:
    engine = Engine([Result(rowcount=1), Result(scalar=501)])

    target_run_id = MysqlCollectionRuntimeRepo(engine).start_target(
        41, 101, "group-20260710-001", NOW
    )

    assert target_run_id == 501
    sql, params = engine.connection.executions[0]
    assert "target_run.status = 'queued'" in sql
    assert "run.status = 'running'" in sql
    assert "target_run.run_id = :run_id" in sql
    assert params["now"] == datetime(2026, 7, 10, 9, 25)


def test_start_target_rejects_terminal_or_wrong_run_without_overwrite() -> None:
    engine = Engine([Result(rowcount=0)])
    with pytest.raises(RuntimeStateError, match="target"):
        MysqlCollectionRuntimeRepo(engine).start_target(
            41, 101, "group-20260710-001", NOW
        )
    assert len(engine.connection.executions) == 1


@pytest.mark.parametrize("status", ["success", "failed", "skipped", "cancelled"])
def test_finish_target_persists_nonnegative_metrics_only_from_running(status) -> None:
    engine = Engine([Result(rowcount=1)])
    outcome = TargetRunOutcome(
        status=status,
        read_count=10,
        insert_count=4,
        duplicate_count=3,
        skipped_count=3,
        error_code="E_RPA" if status == "failed" else None,
        error_summary="safe summary" if status == "failed" else None,
        screenshot_path="D:\\captures\\failure.png" if status == "failed" else None,
    )

    MysqlCollectionRuntimeRepo(engine).finish_target(501, outcome, NOW)

    sql, params = engine.connection.executions[0]
    assert "status = 'running'" in sql
    assert params["status"] == status
    assert params["read_count"] == 10
    assert params["screenshot_path"] in (None, "D:\\captures\\failure.png")


def test_finish_target_desensitizes_error_summary_before_storage() -> None:
    engine = Engine([Result(rowcount=1)])
    MysqlCollectionRuntimeRepo(engine).finish_target(
        501,
        TargetRunOutcome(
            status="failed",
            error_summary="联系13812345678 https://mp.weixin.qq.com/s/raw",
        ),
        NOW,
    )
    summary = engine.connection.executions[0][1]["error_summary"]
    assert "138****5678" in summary
    assert "https://" not in summary
    assert "mp.weixin.qq.com" not in summary


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_finish_target_rejects_invalid_metric_counts(value) -> None:
    outcome = TargetRunOutcome(status="success", read_count=value)
    with pytest.raises((TypeError, ValueError), match="read_count"):
        MysqlCollectionRuntimeRepo(Engine([])).finish_target(501, outcome, NOW)


def test_repeat_identical_finish_target_is_idempotent_without_count_increment() -> None:
    engine = Engine(
        [
            Result(rowcount=0),
            Result(
                rows=[
                    {
                        "status": "success",
                        "read_count": 10,
                        "insert_count": 4,
                        "duplicate_count": 3,
                        "skipped_count": 3,
                        "error_code": None,
                        "error_summary": None,
                        "screenshot_path": None,
                    }
                ]
            ),
        ]
    )
    MysqlCollectionRuntimeRepo(engine).finish_target(
        501,
        TargetRunOutcome(
            status="success",
            read_count=10,
            insert_count=4,
            duplicate_count=3,
            skipped_count=3,
        ),
        NOW,
    )
    assert len(engine.connection.executions) == 2
    assert "SET status" not in engine.connection.executions[1][0]


def test_finish_target_cannot_overwrite_different_terminal_state() -> None:
    engine = Engine(
        [
            Result(rowcount=0),
            Result(
                rows=[
                    {
                        "status": "failed",
                        "read_count": 1,
                        "insert_count": 0,
                        "duplicate_count": 0,
                        "skipped_count": 0,
                        "error_code": "E_RPA",
                        "error_summary": "safe",
                        "screenshot_path": None,
                    }
                ]
            ),
        ]
    )
    with pytest.raises(RuntimeStateError, match="target"):
        MysqlCollectionRuntimeRepo(engine).finish_target(
            501, TargetRunOutcome(status="success"), NOW
        )


def test_finish_run_uses_terminal_guard_and_reconciles_target_counts() -> None:
    engine = Engine([Result(rowcount=1), Result(rowcount=0)])

    MysqlCollectionRuntimeRepo(engine).finish_run(41, RunStatus.PARTIAL_SUCCESS, NOW)

    sql, params = engine.connection.executions[0]
    assert "status = 'running'" in sql
    assert "target_success_count" in sql
    assert "target_failed_count" in sql
    assert "status = 'success'" in sql
    assert "status IN ('failed', 'cancelled')" in sql
    assert "NOT EXISTS" in sql
    assert "status IN ('queued', 'running')" in sql
    assert params["status"] == "partial_success"
    stop_sql, _ = engine.connection.executions[1]
    assert "status = 'stop_requested'" in stop_sql
    assert "status = 'stopped'" in stop_sql


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.QUEUED])
def test_finish_run_rejects_nonterminal_status(status) -> None:
    with pytest.raises(ValueError, match="terminal"):
        MysqlCollectionRuntimeRepo(Engine([])).finish_run(41, status, NOW)


@pytest.mark.parametrize(
    "status", [RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS]
)
def test_repeat_same_terminal_finish_run_is_idempotent_without_extra_write(
    status,
) -> None:
    engine = Engine(
        [Result(rowcount=0), Result(rows=[{"status": status.value}])]
    )

    MysqlCollectionRuntimeRepo(engine).finish_run(41, status, NOW)

    assert len(engine.connection.executions) == 2
    lookup_sql, lookup_params = engine.connection.executions[1]
    assert "SELECT status" in lookup_sql
    assert lookup_params == {"run_id": 41}
    assert all("UPDATE wechat_collection_job job" not in sql for sql, _ in engine.connection.executions)


def test_finish_run_rejects_different_terminal_without_overwrite() -> None:
    engine = Engine(
        [Result(rowcount=0), Result(rows=[{"status": "failed"}])]
    )
    with pytest.raises(RuntimeStateError, match="run"):
        MysqlCollectionRuntimeRepo(engine).finish_run(
            41, RunStatus.SUCCESS, NOW
        )
    assert len(engine.connection.executions) == 2


def test_finish_run_rejects_unknown_run_without_extra_write() -> None:
    engine = Engine([Result(rowcount=0), Result(rows=[])])
    with pytest.raises(RuntimeStateError, match="run"):
        MysqlCollectionRuntimeRepo(engine).finish_run(
            41, RunStatus.SUCCESS, NOW
        )
    assert len(engine.connection.executions) == 2


def test_finish_run_rejects_running_run_with_unfinished_targets() -> None:
    engine = Engine(
        [Result(rowcount=0), Result(rows=[{"status": "running"}])]
    )
    with pytest.raises(RuntimeStateError, match="run"):
        MysqlCollectionRuntimeRepo(engine).finish_run(41, RunStatus.SUCCESS, NOW)
    assert len(engine.connection.executions) == 2


def test_abort_expired_runs_locks_then_closes_only_nonterminal_rows_and_logs() -> None:
    engine = Engine(
        [
            Result(rows=[{"run_id": 41, "job_id": 7, "worker_id": "collector-1"}]),
            Result(rowcount=2),
            Result(rowcount=1),
            Result(),
        ]
    )

    count = MysqlCollectionRuntimeRepo(engine).abort_expired_runs(NOW)

    assert count == 1
    select_sql, select_params = engine.connection.executions[0]
    assert "status = 'running'" in select_sql
    assert "lease_expires_at <= :now" in select_sql
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert select_params == {"now": datetime(2026, 7, 10, 9, 25)}
    target_sql, target_params = engine.connection.executions[1]
    assert "status IN ('queued', 'running')" in target_sql
    assert "status = 'cancelled'" in target_sql
    assert target_params["run_id_0"] == 41
    run_sql, _ = engine.connection.executions[2]
    assert "status = 'aborted'" in run_sql
    assert "status = 'running'" in run_sql
    assert "target_success_count" in run_sql
    assert "target_failed_count" in run_sql
    event_sql, event_params = engine.connection.executions[3]
    assert "collection_run_lease_expired" == event_params[0]["event_type"]
    assert "wechat_collection_job_event" in event_sql


def test_abort_expired_runs_returns_zero_without_writes() -> None:
    engine = Engine([Result(rows=[])])
    assert MysqlCollectionRuntimeRepo(engine).abort_expired_runs(NOW) == 0
    assert len(engine.connection.executions) == 1


@pytest.mark.parametrize("method,args", [
    ("heartbeat_run", (True, "collector-1", NOW, 120)),
    ("is_stop_requested", (True,)),
    ("start_target", (41, True, "batch", NOW)),
    ("finish_target", (True, TargetRunOutcome(status="success"), NOW)),
    ("finish_run", (True, RunStatus.SUCCESS, NOW)),
])
def test_runtime_methods_reject_boolean_ids(method, args) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        getattr(MysqlCollectionRuntimeRepo(Engine([])), method)(*args)
