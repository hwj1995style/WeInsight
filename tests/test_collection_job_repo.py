from __future__ import annotations

import json
import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.collection_jobs import JobStatus, PipelineType, ScheduleSpec
from app.services.collection_job_service import (
    CreateCollectionJobCommand,
    JobListFilter,
    JobMixedPipelineError,
    ManagedJobMutationError,
    JobNotFoundError,
    JobOverlapError,
    JobStateTransitionError,
    JobTargetDisabledError,
    JobTargetNotFoundError,
    JobVersionConflictError,
)
from app.storage.collection_job_repo import MysqlCollectionJobRepo


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 0, tzinfo=ZONE)


def command(**overrides) -> CreateCollectionJobCommand:
    values = {
        "job_name": "晨间任务",
        "pipeline_type": PipelineType.GROUP,
        "target_ids": (9, 7),
        "effective_start_at": NOW,
        "effective_end_at": datetime(2026, 7, 12, 18, 0, tzinfo=ZONE),
        "daily_window_start": time(9, 0),
        "daily_window_end": time(18, 0),
        "interval_seconds": 600,
    }
    values.update(overrides)
    return CreateCollectionJobCommand(**values)


def group_row(source_id: int, name: str, priority: int, **changes):
    row = {
        "id": source_id,
        "source_name": name,
        "enabled": 1,
        "priority": priority,
        "poll_interval_seconds": 30,
        "backtrack_pages": 4,
        "extra_backtrack_pages": 8,
        "is_core_group": 1,
        "remark": None,
    }
    row.update(changes)
    return row


def article_row(source_id: int, **changes):
    row = {
        "id": source_id,
        "source_name": "行业观察",
        "enabled": 1,
        "priority": 3,
        "account_type": "subscription",
        "feed_url": "http://127.0.0.1:8001/feed/industry.xml",
        "source_type": "rss",
        "request_timeout_seconds": 30,
        "poll_interval_minutes": 10,
        "daily_window_start": timedelta(hours=7, minutes=30),
        "daily_window_end": time(19, 30),
        "max_articles_per_round": 5,
        "collect_today_only": 1,
        "dedup_key": "article_hash",
        "remark": None,
    }
    row.update(changes)
    return row


class Result:
    def __init__(
        self,
        *,
        rows=None,
        rowcount=1,
        lastrowid=None,
        scalar=None,
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
        return next(self.results)

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


class ConcurrentSystemEngine:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2)
        self.jobs: list[dict] = []
        self.targets: dict[int, tuple[int, ...]] = {}
        self.next_id = 40

    def begin(self):
        return ConcurrentSystemConnection(self)


class ConcurrentSystemConnection:
    def __init__(self, engine: ConcurrentSystemEngine) -> None:
        self.engine = engine
        self.locked = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.locked:
            self.engine.lock.release()
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM wechat_system_job_coordination" in sql:
            self.engine.barrier.wait(timeout=2)
            self.engine.lock.acquire()
            self.locked = True
            return Result(rows=[{"coordination_key": "article_global"}])
        if "WHERE job.managed_key" in sql:
            current = next(
                (job for job in self.engine.jobs if job["managed_key"]), None
            )
            if current is None:
                return Result(rows=[])
            ids = self.engine.targets.get(current["id"], ())
            return Result(rows=[{
                "id": current["id"],
                "status": current["status"],
                "target_ids": ",".join(map(str, ids)),
            }])
        if "FROM wechat_collection_job_run" in sql:
            return Result(rows=[])
        if "FROM wechat_public_account_config" in sql:
            return Result(rows=[article_row(params["source_id"])])
        if "INSERT INTO wechat_collection_job (" in sql:
            self.engine.next_id += 1
            self.engine.jobs.append({
                "id": self.engine.next_id,
                "managed_key": params["managed_key"],
                "status": params["status"],
            })
            return Result(lastrowid=self.engine.next_id)
        if "INSERT INTO wechat_collection_job_target" in sql:
            rows = params
            self.engine.targets[rows[0]["job_id"]] = tuple(
                row["article_config_id"] for row in rows
            )
            return Result()
        if "UPDATE wechat_collection_job" in sql:
            return Result()
        raise AssertionError(sql)


def create_results(*source_rows):
    return [
        *(Result(rows=[row]) for row in source_rows),
        Result(rows=[]),
        Result(lastrowid=41),
        Result(),
        Result(),
    ]


def test_create_locks_deduplicated_sources_then_checks_overlap_before_insert() -> None:
    engine = Engine(
        create_results(
            group_row(7, "乙群", 2),
            group_row(9, "甲群", 1),
        )
    )

    job_id = MysqlCollectionJobRepo(engine).create_job(
        command(target_ids=(9, 7, 9)),
        JobStatus.ACTIVE,
        NOW,
        "admin",
    )

    assert job_id == 41
    assert engine.begin_count == 1
    executions = engine.connection.executions
    assert all("FOR UPDATE" in executions[index][0] for index in (0, 1))
    assert [executions[index][1]["source_id"] for index in (0, 1)] == [7, 9]
    assert "status IN ('scheduled', 'active', 'stop_requested')" in executions[2][0]
    assert "INSERT INTO wechat_collection_job" in executions[3][0]
    assert "INSERT INTO wechat_collection_job_target" in executions[4][0]
    target_params = executions[4][1]
    assert [row["source_id"] for row in target_params] == [9, 7]
    assert [row["target_name_snapshot"] for row in target_params] == [
        "甲群",
        "乙群",
    ]
    assert all(row["article_config_id"] is None for row in target_params)
    assert executions[3][1]["effective_start_at"].tzinfo is None
    assert executions[3][1]["next_run_at"].tzinfo is None


def test_system_reconcile_defers_target_switch_while_old_run_is_live() -> None:
    engine = Engine([
        Result(rows=[{"coordination_key": "article_global"}]),
        Result(rows=[{"id": 41, "status": "active", "target_ids": "7"}]),
        Result(rows=[{"id": 99}]),
        Result(),
    ])

    MysqlCollectionJobRepo(engine).reconcile_system_article_job((8,), 10, NOW)

    sql = [item[0] for item in engine.connection.executions]
    assert "wechat_system_job_coordination" in sql[0]
    assert "FOR UPDATE" in sql[0]
    assert "queued', 'running" in sql[2]
    assert "JOIN wechat_collection_job" in sql[2]
    assert "job.job_name = :job_name" in sql[2]
    assert "stop_requested" in sql[3]
    assert all("INSERT INTO wechat_collection_job_target" not in item for item in sql)
    assert all("completed" not in item for item in sql)


def test_system_reconcile_refuses_to_run_without_seeded_coordination_row() -> None:
    engine = Engine([Result(rows=[])])

    with pytest.raises(RuntimeError, match="coordination row"):
        MysqlCollectionJobRepo(engine).reconcile_system_article_job((8,), 10, NOW)

    assert len(engine.connection.executions) == 1


def test_system_reconcile_serializes_then_rotates_after_runs_are_terminal() -> None:
    engine = Engine([
        Result(rows=[{"coordination_key": "article_global"}]),
        Result(rows=[{"id": 41, "status": "stopped", "target_ids": "7"}]),
        Result(rows=[]),
        Result(),
        Result(rows=[article_row(8)]),
        Result(lastrowid=42),
        Result(),
    ])

    MysqlCollectionJobRepo(engine).reconcile_system_article_job((8,), 10, NOW)

    sql = [item[0] for item in engine.connection.executions]
    assert "managed_key = NULL" in sql[3]
    assert "status = 'completed'" in sql[3]
    assert "managed_key" in sql[5]
    assert engine.connection.executions[5][1]["managed_key"] == "article_global"
    assert "INSERT INTO wechat_collection_job_target" in sql[6]


def test_two_collectors_first_reconcile_create_one_runnable_system_job() -> None:
    engine = ConcurrentSystemEngine()
    errors = []

    def reconcile():
        try:
            MysqlCollectionJobRepo(engine).reconcile_system_article_job((8,), 10, NOW)
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    threads = [threading.Thread(target=reconcile) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert errors == []
    assert len([job for job in engine.jobs if job["managed_key"]]) == 1
    assert list(engine.targets.values()) == [(8,)]


def test_two_creation_transactions_use_same_exclusive_lock_then_overlap_protocol() -> None:
    engines = [
        Engine(create_results(group_row(7, "核心群", 1))),
        Engine(create_results(group_row(7, "核心群", 1))),
    ]

    for engine in engines:
        MysqlCollectionJobRepo(engine).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )

    for engine in engines:
        statements = [sql for sql, _ in engine.connection.executions]
        assert "FOR UPDATE" in statements[0]
        assert "wechat_group_config" in statements[0]
        assert "SELECT DISTINCT" in statements[1]
        assert "INSERT INTO wechat_collection_job" in statements[2]


def test_create_builds_canonical_safe_article_snapshot_from_locked_row() -> None:
    engine = Engine(create_results(article_row(9)))

    MysqlCollectionJobRepo(engine).create_job(
        command(
            pipeline_type=PipelineType.ARTICLE,
            target_ids=(9,),
            interval_seconds=600,
        ),
        JobStatus.ACTIVE,
        NOW,
        "admin",
    )

    params = engine.connection.executions[3][1][0]
    assert params["group_config_id"] is None
    assert params["article_config_id"] == 9
    assert params["config_snapshot_json"] == (
        '{"account_type":"subscription","collect_today_only":true,'
        '"daily_window_end":"19:30:00","daily_window_start":"07:30:00",'
        '"dedup_key":"article_hash","feed_url":"http://127.0.0.1:8001/feed/industry.xml",'
        '"max_articles_per_round":5,"poll_interval_minutes":10,'
        '"remark":null,"request_timeout_seconds":30,"source_type":"rss"}'
    )
    assert "password" not in params["config_snapshot_json"].lower()


def test_create_rejects_actual_overlapping_candidate_before_any_insert() -> None:
    overlap_row = {
        "id": 12,
        "job_name": "已有晨间任务",
        "effective_start_at": datetime(2026, 7, 10, 8, 0),
        "effective_end_at": datetime(2026, 7, 11, 10, 0),
        "daily_window_start": timedelta(hours=8),
        "daily_window_end": "10:00:00",
        "interval_seconds": 300,
    }
    engine = Engine(
        [
            Result(rows=[group_row(7, "核心群", 1)]),
            Result(rows=[overlap_row]),
        ]
    )

    with pytest.raises(JobOverlapError) as exc:
        MysqlCollectionJobRepo(engine).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )

    assert exc.value.job_names == ("已有晨间任务",)
    assert len(engine.connection.executions) == 2


def test_create_ignores_candidate_with_nonoverlapping_daily_window() -> None:
    candidate = {
        "id": 12,
        "job_name": "晚间任务",
        "effective_start_at": datetime(2026, 7, 10, 8, 0),
        "effective_end_at": datetime(2026, 7, 11, 22, 0),
        "daily_window_start": time(20, 0),
        "daily_window_end": time(22, 0),
        "interval_seconds": 300,
    }
    engine = Engine(
        [
            Result(rows=[group_row(7, "核心群", 1)]),
            Result(rows=[candidate]),
            Result(lastrowid=41),
            Result(),
            Result(),
        ]
    )

    assert (
        MysqlCollectionJobRepo(engine).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )
        == 41
    )


def test_create_maps_missing_disabled_and_wrong_pipeline_to_safe_errors() -> None:
    missing = Engine([Result(rows=[]), Result(rows=[])])
    with pytest.raises(JobTargetNotFoundError):
        MysqlCollectionJobRepo(missing).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )
    assert "FOR UPDATE" not in missing.connection.executions[1][0]
    assert "FOR SHARE" not in missing.connection.executions[1][0]

    disabled = Engine([Result(rows=[group_row(7, "核心群", 1, enabled=0)])])
    with pytest.raises(JobTargetDisabledError):
        MysqlCollectionJobRepo(disabled).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )

    mixed = Engine([Result(rows=[]), Result(rows=[{"id": 7}])])
    with pytest.raises(JobMixedPipelineError, match="same pipeline"):
        MysqlCollectionJobRepo(mixed).create_job(
            command(target_ids=(7,)), JobStatus.ACTIVE, NOW, "admin"
        )
    assert "FOR UPDATE" not in mixed.connection.executions[1][0]
    assert "FOR SHARE" not in mixed.connection.executions[1][0]


@pytest.mark.parametrize(
    ("current", "has_active_run", "expected", "target"),
    [
        (JobStatus.SCHEDULED, False, 3, JobStatus.STOPPED),
        (JobStatus.ACTIVE, True, 3, JobStatus.STOP_REQUESTED),
        (JobStatus.ACTIVE, False, 3, JobStatus.STOPPED),
    ],
)
def test_stop_locks_and_updates_legal_state_with_version(
    current, has_active_run, expected, target
) -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    {
                        "status": current.value,
                        "version": expected,
                        "has_active_run": has_active_run,
                    }
                ]
            ),
            Result(rowcount=1),
            Result(),
        ]
    )

    result = MysqlCollectionJobRepo(engine).request_stop(
        11, expected, "admin", NOW
    )

    assert result is target
    lock_sql, _ = engine.connection.executions[0]
    update_sql, params = engine.connection.executions[1]
    assert "FOR UPDATE" in lock_sql
    assert "WHERE id = :job_id" in update_sql
    assert "AND version = :expected_version" in update_sql
    assert "version = version + 1" in update_sql
    assert params["status"] == target.value
    assert params["now"].tzinfo is None


@pytest.mark.parametrize("status", [JobStatus.STOP_REQUESTED, JobStatus.STOPPED])
def test_repeated_stop_is_idempotent_even_with_stale_version(status) -> None:
    engine = Engine([Result(rows=[{"status": status.value, "version": 9}])])

    result = MysqlCollectionJobRepo(engine).request_stop(11, 1, "admin", NOW)

    assert result is status
    assert len(engine.connection.executions) == 1


def test_stop_distinguishes_missing_version_conflict_and_illegal_state() -> None:
    missing = Engine([Result(rows=[])])
    with pytest.raises(JobNotFoundError):
        MysqlCollectionJobRepo(missing).request_stop(11, 3, "admin", NOW)

    conflict = Engine(
        [Result(rows=[{"status": "active", "version": 4}])]
    )
    with pytest.raises(JobVersionConflictError):
        MysqlCollectionJobRepo(conflict).request_stop(11, 3, "admin", NOW)

    illegal = Engine(
        [Result(rows=[{"status": "completed", "version": 3}])]
    )
    with pytest.raises(JobStateTransitionError):
        MysqlCollectionJobRepo(illegal).request_stop(11, 3, "admin", NOW)


@pytest.mark.parametrize("status", [JobStatus.STOPPED, JobStatus.COMPLETED])
def test_delete_only_allows_terminal_state_and_uses_version(status) -> None:
    engine = Engine(
        [
            Result(rows=[{"status": status.value, "version": 4}]),
            Result(rowcount=1),
            Result(),
        ]
    )

    assert MysqlCollectionJobRepo(engine).soft_delete(11, 4, "admin", NOW)

    sql, params = engine.connection.executions[1]
    assert "status = 'deleted'" in sql
    assert "AND version = :expected_version" in sql
    assert "version = version + 1" in sql
    assert params["deleted_at"].tzinfo is None


def test_repeated_delete_is_idempotent_and_active_delete_is_rejected() -> None:
    deleted = Engine([Result(rows=[{"status": "deleted", "version": 9}])])
    assert MysqlCollectionJobRepo(deleted).soft_delete(11, 1, "admin", NOW)
    assert len(deleted.connection.executions) == 1

    active = Engine([Result(rows=[{"status": "active", "version": 4}])])
    with pytest.raises(JobStateTransitionError):
        MysqlCollectionJobRepo(active).soft_delete(11, 4, "admin", NOW)


@pytest.mark.parametrize("method", ["request_stop", "soft_delete"])
def test_repository_rejects_system_managed_job_mutation_under_row_lock(method) -> None:
    engine = Engine([Result(rows=[{
        "status": "active", "version": 1, "managed_key": "article_global"
    }])])

    with pytest.raises(ManagedJobMutationError):
        getattr(MysqlCollectionJobRepo(engine), method)(11, 1, "admin", NOW)

    assert len(engine.connection.executions) == 1
    assert "FOR UPDATE" in engine.connection.executions[0][0]


def test_get_job_attaches_shanghai_timezone_and_normalizes_mysql_times() -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    {
                        "id": 11,
                        "job_name": "晨间任务",
                        "pipeline_type": "group",
                        "effective_start_at": datetime(2026, 7, 10, 9, 0),
                        "effective_end_at": datetime(2026, 7, 12, 18, 0),
                        "daily_window_start": timedelta(hours=9),
                        "daily_window_end": "18:00:00",
                        "interval_seconds": 600,
                        "status": "active",
                        "next_run_at": datetime(2026, 7, 10, 9, 10),
                        "version": 3,
                    }
                ]
            ),
            Result(rows=[{"target_name_snapshot": "甲群"}, {"target_name_snapshot": "乙群"}]),
        ]
    )

    detail = MysqlCollectionJobRepo(engine).get_job(11)

    assert detail is not None
    assert detail.schedule.effective_start_at.tzinfo == ZONE
    assert detail.schedule.daily_window_start == time(9, 0)
    assert detail.schedule.daily_window_end == time(18, 0)
    assert detail.next_run_at == datetime(2026, 7, 10, 9, 10, tzinfo=ZONE)
    assert detail.target_names == ("甲群", "乙群")
    target_sql = engine.connection.executions[1][0]
    assert "ORDER BY priority_snapshot ASC, target_name_snapshot ASC, id ASC" in target_sql
    assert "raw" not in target_sql.lower()


def test_list_jobs_reuses_filter_params_escapes_like_and_has_stable_order() -> None:
    engine = Engine(
        [
            Result(scalar=1),
            Result(
                rows=[
                    {
                        "id": 11,
                        "job_name": "100%_群\\",
                        "pipeline_type": "group",
                        "status": "active",
                        "next_run_at": datetime(2026, 7, 10, 9, 10),
                        "target_count": 2,
                        "version": 3,
                    }
                ]
            ),
        ]
    )
    filters = JobListFilter(
        pipeline_type=PipelineType.GROUP,
        status=JobStatus.ACTIVE,
        name_contains="100%_群\\",
        date=date(2026, 7, 10),
    )

    page = MysqlCollectionJobRepo(engine).list_jobs(filters, 2, 20)

    assert page.total_count == 1
    count_sql, count_params = engine.connection.executions[0]
    data_sql, data_params = engine.connection.executions[1]
    assert "job_name LIKE :name_contains ESCAPE" in count_sql
    assert "effective_start_at < :date_end_exclusive" in count_sql
    assert "effective_end_at > :date_start_inclusive" in count_sql
    assert "ORDER BY update_time DESC, id DESC" in data_sql
    assert "raw" not in data_sql.lower()
    assert count_params == {
        "pipeline_type": "group",
        "status": "active",
        "name_contains": "%100\\%\\_群\\\\%",
        "date_start_inclusive": datetime(2026, 7, 10, 0, 0),
        "date_end_exclusive": datetime(2026, 7, 11, 0, 0),
    }
    assert data_params == {
        **count_params,
        "limit": 20,
        "offset": 20,
    }
    assert page.items[0].next_run_at.tzinfo == ZONE


def test_list_jobs_default_excludes_deleted_but_explicit_deleted_is_queryable() -> None:
    default_engine = Engine([Result(scalar=0), Result(rows=[])])

    MysqlCollectionJobRepo(default_engine).list_jobs(JobListFilter(), 1, 20)

    default_count_sql, default_count_params = default_engine.connection.executions[0]
    default_data_sql, default_data_params = default_engine.connection.executions[1]
    assert "status <> 'deleted'" in default_count_sql
    assert "status <> 'deleted'" in default_data_sql
    assert "status" not in default_count_params
    assert default_data_params == {"limit": 20, "offset": 0}

    deleted_engine = Engine([Result(scalar=0), Result(rows=[])])
    MysqlCollectionJobRepo(deleted_engine).list_jobs(
        JobListFilter(status=JobStatus.DELETED), 1, 20
    )

    deleted_count_sql, deleted_count_params = deleted_engine.connection.executions[0]
    deleted_data_sql, deleted_data_params = deleted_engine.connection.executions[1]
    assert "status = :status" in deleted_count_sql
    assert "status <> 'deleted'" not in deleted_count_sql
    assert "status <> 'deleted'" not in deleted_data_sql
    assert deleted_count_params == {"status": "deleted"}
    assert deleted_data_params == {"status": "deleted", "limit": 20, "offset": 0}


def test_date_filter_uses_half_open_effective_interval_boundaries() -> None:
    engine = Engine([Result(scalar=0), Result(rows=[])])

    MysqlCollectionJobRepo(engine).list_jobs(
        JobListFilter(date=date(2026, 7, 10)), 1, 20
    )

    sql, params = engine.connection.executions[0]
    assert "effective_start_at < :date_end_exclusive" in sql
    assert "effective_end_at > :date_start_inclusive" in sql
    assert params == {
        "date_start_inclusive": datetime(2026, 7, 10, 0, 0),
        "date_end_exclusive": datetime(2026, 7, 11, 0, 0),
    }
