from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    PipelineType,
    RunStatus,
    ScheduleSpec,
    ensure_schedule_datetime,
)
from app.services.collection_schedule import coalesced_scheduled_at, next_run_at
from app.storage.collection_event_repo import sanitize_output


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_TARGET_TERMINAL = frozenset({"success", "failed", "skipped", "cancelled"})
_RUN_TERMINAL = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.PARTIAL_SUCCESS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.ABORTED,
    }
)


class RuntimeStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimedTarget:
    job_target_id: int
    source_id: int
    source_name: str
    priority: int
    config_snapshot_json: str


@dataclass(frozen=True, slots=True)
class ClaimedCollectionRun:
    run_id: int
    job_id: int
    job_name: str
    pipeline_type: PipelineType
    scheduled_at: datetime
    status: RunStatus
    targets: tuple[ClaimedTarget, ...]


@dataclass(frozen=True, slots=True)
class TargetRunOutcome:
    status: str
    read_count: int = 0
    insert_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    error_code: str | None = None
    error_summary: str | None = None
    screenshot_path: str | None = None


class MysqlCollectionRuntimeRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim_next_due(
        self,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedCollectionRun | None:
        _shanghai_datetime(now, "now")
        _required_text(worker_id, "worker_id", 100)
        _positive_integer(lease_seconds, "lease_seconds")
        db_now = _to_db_datetime(now)
        with self.engine.begin() as connection:
            row = connection.execute(_LOCK_NEXT_DUE, {"now": db_now}).mappings().first()
            if row is None:
                return None
            spec = _schedule_from_row(row)
            previous_next = _db_datetime(row["next_run_at"])
            scheduled_at = coalesced_scheduled_at(
                spec,
                now=now,
                previous_next_run=previous_next,
            )
            if scheduled_at is None:
                next_at = next_run_at(
                    spec,
                    after=now,
                    anchor=spec.effective_start_at,
                )
                _advance_without_run(connection, int(row["job_id"]), next_at)
                return None

            try:
                insert = connection.execute(
                    _INSERT_RUN,
                    {
                        "job_id": int(row["job_id"]),
                        "scheduled_at": _to_db_datetime(scheduled_at),
                        "worker_id": worker_id,
                        "lease_expires_at": _to_db_datetime(
                            now + timedelta(seconds=lease_seconds)
                        ),
                        "now": db_now,
                        "target_total_count": int(row["target_total_count"]),
                    },
                )
            except IntegrityError as exc:
                if _is_schedule_duplicate(exc):
                    return None
                raise
            run_id = int(insert.lastrowid)
            target_rows = connection.execute(
                _SELECT_TARGET_SNAPSHOTS,
                {"job_id": int(row["job_id"])},
            ).mappings().all()
            targets = tuple(_claimed_target_from_row(item) for item in target_rows)
            if len(targets) != int(row["target_total_count"]):
                raise RuntimeStateError("job target snapshot count changed during claim")
            connection.execute(
                _INSERT_TARGET_RUN,
                [
                    {"run_id": run_id, "job_target_id": target.job_target_id}
                    for target in targets
                ],
            )
            next_at = next_run_at(
                spec,
                after=scheduled_at,
                anchor=spec.effective_start_at,
            )
            _advance_after_run(connection, int(row["job_id"]), next_at)
            missed_count = _count_missed_periods(spec, previous_next, scheduled_at)
            if missed_count:
                connection.execute(
                    _INSERT_MISFIRE_EVENT,
                    {
                        "job_id": int(row["job_id"]),
                        "run_id": run_id,
                        "worker_id": worker_id,
                        "event_type": "misfire",
                        "message": "missed schedules coalesced into latest eligible run",
                        "metrics_json": json.dumps(
                            {"missed_count": missed_count},
                            separators=(",", ":"),
                        ),
                    },
                )
            return ClaimedCollectionRun(
                run_id=run_id,
                job_id=int(row["job_id"]),
                job_name=str(row["job_name"]),
                pipeline_type=PipelineType(str(row["pipeline_type"])),
                scheduled_at=scheduled_at,
                status=RunStatus.RUNNING,
                targets=targets,
            )

    def heartbeat_run(
        self,
        run_id: int,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        _positive_integer(run_id, "run_id")
        _required_text(worker_id, "worker_id", 100)
        _shanghai_datetime(now, "now")
        _positive_integer(lease_seconds, "lease_seconds")
        with self.engine.begin() as connection:
            result = connection.execute(
                _HEARTBEAT_RUN,
                {
                    "run_id": run_id,
                    "worker_id": worker_id,
                    "lease_expires_at": _to_db_datetime(
                        now + timedelta(seconds=lease_seconds)
                    ),
                },
            )
            return int(result.rowcount or 0) == 1

    def is_stop_requested(self, job_id: int) -> bool:
        _positive_integer(job_id, "job_id")
        with self.engine.begin() as connection:
            return bool(
                connection.execute(_IS_STOP_REQUESTED, {"job_id": job_id}).scalar_one()
            )

    def start_target(
        self,
        run_id: int,
        job_target_id: int,
        batch_id: str,
        now: datetime,
    ) -> int:
        _positive_integer(run_id, "run_id")
        _positive_integer(job_target_id, "job_target_id")
        _required_text(batch_id, "batch_id", 64)
        _shanghai_datetime(now, "now")
        with self.engine.begin() as connection:
            result = connection.execute(
                _START_TARGET,
                {
                    "run_id": run_id,
                    "job_target_id": job_target_id,
                    "batch_id": batch_id,
                    "now": _to_db_datetime(now),
                },
            )
            if int(result.rowcount or 0) != 1:
                raise RuntimeStateError("target is not queued in a running run")
            return int(
                connection.execute(
                    _GET_TARGET_RUN_ID,
                    {"run_id": run_id, "job_target_id": job_target_id},
                ).scalar_one()
            )

    def finish_target(
        self,
        target_run_id: int,
        outcome: TargetRunOutcome,
        now: datetime,
    ) -> None:
        _positive_integer(target_run_id, "target_run_id")
        _validate_outcome(outcome)
        _shanghai_datetime(now, "now")
        safe_error_summary = (
            None
            if outcome.error_summary is None
            else sanitize_output(outcome.error_summary)
        )
        outcome_params = {
            "status": outcome.status,
            "read_count": outcome.read_count,
            "insert_count": outcome.insert_count,
            "duplicate_count": outcome.duplicate_count,
            "skipped_count": outcome.skipped_count,
            "error_code": outcome.error_code,
            "error_summary": safe_error_summary,
            "screenshot_path": outcome.screenshot_path,
        }
        with self.engine.begin() as connection:
            result = connection.execute(
                _FINISH_TARGET,
                {
                    "target_run_id": target_run_id,
                    **outcome_params,
                    "now": _to_db_datetime(now),
                },
            )
            if int(result.rowcount or 0) != 1:
                row = connection.execute(
                    _GET_TARGET_OUTCOME,
                    {"target_run_id": target_run_id},
                ).mappings().first()
                if row is not None and _outcome_matches(row, outcome_params):
                    return
                raise RuntimeStateError("target is not running or outcome differs")

    def finish_run(self, run_id: int, status: RunStatus, now: datetime) -> None:
        _positive_integer(run_id, "run_id")
        if not isinstance(status, RunStatus) or status not in _RUN_TERMINAL:
            raise ValueError("status must be a terminal RunStatus")
        _shanghai_datetime(now, "now")
        with self.engine.begin() as connection:
            result = connection.execute(
                _FINISH_RUN,
                {"run_id": run_id, "status": status.value, "now": _to_db_datetime(now)},
            )
            if int(result.rowcount or 0) != 1:
                row = connection.execute(
                    _GET_RUN_STATUS,
                    {"run_id": run_id},
                ).mappings().first()
                if row is not None and str(row["status"]) == status.value:
                    return
                raise RuntimeStateError("run is not running")
            connection.execute(_SET_STOPPED_AFTER_RUN, {"run_id": run_id})

    def abort_expired_runs(self, now: datetime) -> int:
        _shanghai_datetime(now, "now")
        db_now = _to_db_datetime(now)
        with self.engine.begin() as connection:
            rows = connection.execute(_LOCK_EXPIRED_RUNS, {"now": db_now}).mappings().all()
            if not rows:
                return 0
            ids = [int(row["run_id"]) for row in rows]
            placeholders = ", ".join(f":run_id_{index}" for index in range(len(ids)))
            params = {f"run_id_{index}": run_id for index, run_id in enumerate(ids)}
            params["now"] = db_now
            connection.execute(
                text(
                    f"""
                    UPDATE wechat_collection_job_target_run
                    SET status = 'cancelled', end_time = :now
                    WHERE run_id IN ({placeholders})
                      AND status IN ('queued', 'running')
                    """
                ),
                params,
            )
            run_result = connection.execute(
                text(
                    f"""
                    UPDATE wechat_collection_job_run run
                    SET run.status = 'aborted', run.end_time = :now,
                        run.lease_expires_at = NULL,
                        run.target_success_count = (
                            SELECT COUNT(*)
                            FROM wechat_collection_job_target_run target
                            WHERE target.run_id = run.id
                              AND target.status = 'success'
                        ),
                        run.target_failed_count = (
                            SELECT COUNT(*)
                            FROM wechat_collection_job_target_run target
                            WHERE target.run_id = run.id
                              AND target.status IN ('failed', 'cancelled')
                        )
                    WHERE run.id IN ({placeholders})
                      AND run.status = 'running'
                    """
                ),
                params,
            )
            connection.execute(
                _INSERT_RECOVERY_EVENT,
                [
                    {
                        "job_id": int(row["job_id"]),
                        "run_id": int(row["run_id"]),
                        "worker_id": row.get("worker_id"),
                        "event_type": "collection_run_lease_expired",
                        "message": "expired collection run was aborted",
                    }
                    for row in rows
                ],
            )
            return int(run_result.rowcount or 0)


def _advance_without_run(connection, job_id: int, next_at: datetime | None) -> None:
    if next_at is None:
        connection.execute(_COMPLETE_JOB, {"job_id": job_id})
    else:
        connection.execute(
            _ADVANCE_JOB,
            {"job_id": job_id, "next_run_at": _to_db_datetime(next_at)},
        )


def _advance_after_run(connection, job_id: int, next_at: datetime | None) -> None:
    _advance_without_run(connection, job_id, next_at)


def _schedule_from_row(row) -> ScheduleSpec:
    return ScheduleSpec(
        effective_start_at=_db_datetime(row["effective_start_at"]),
        effective_end_at=_db_datetime(row["effective_end_at"]),
        daily_window_start=_db_time(row["daily_window_start"]),
        daily_window_end=_db_time(row["daily_window_end"]),
        interval_seconds=int(row["interval_seconds"]),
        timezone=APPLICATION_TIMEZONE,
    )


def _claimed_target_from_row(row) -> ClaimedTarget:
    return ClaimedTarget(
        job_target_id=int(row["job_target_id"]),
        source_id=int(row["source_id"]),
        source_name=str(row["source_name"]),
        priority=int(row["priority"]),
        config_snapshot_json=str(row["config_snapshot_json"]),
    )


def _count_missed_periods(
    spec: ScheduleSpec,
    first_due: datetime,
    coalesced: datetime,
) -> int:
    lower = max(first_due, spec.effective_start_at)
    upper = min(coalesced, spec.effective_end_at)
    if lower >= upper:
        return 0
    interval_microseconds = spec.interval_seconds * 1_000_000
    total = 0
    day = lower.date()
    last_day = (upper - timedelta(microseconds=1)).date()
    while day <= last_day:
        midnight = datetime.combine(day, time.min, tzinfo=_ZONE)
        for segment_start, segment_end in _daily_segments(spec, midnight):
            start = max(lower, segment_start)
            end = min(upper, segment_end)
            if start < end:
                total += _grid_count(
                    spec.effective_start_at,
                    interval_microseconds,
                    start,
                    end,
                )
        day += timedelta(days=1)
    return total


def _daily_segments(
    spec: ScheduleSpec,
    midnight: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    next_midnight = midnight + timedelta(days=1)
    start = datetime.combine(
        midnight.date(), spec.daily_window_start, tzinfo=_ZONE
    )
    end = datetime.combine(
        midnight.date(), spec.daily_window_end, tzinfo=_ZONE
    )
    if spec.daily_window_start == spec.daily_window_end:
        return ((midnight, next_midnight),)
    if spec.daily_window_start < spec.daily_window_end:
        return ((start, end),)
    return ((midnight, end), (start, next_midnight))


def _grid_count(
    anchor: datetime,
    interval_microseconds: int,
    start: datetime,
    end: datetime,
) -> int:
    first = _ceil_div(
        _timedelta_microseconds(start - anchor), interval_microseconds
    )
    past_last = _ceil_div(
        _timedelta_microseconds(end - anchor), interval_microseconds
    )
    return max(0, past_last - first)


def _timedelta_microseconds(value: timedelta) -> int:
    return (
        (value.days * 86_400 + value.seconds) * 1_000_000
        + value.microseconds
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return -((-numerator) // denominator)


def _validate_outcome(outcome: object) -> None:
    if not isinstance(outcome, TargetRunOutcome):
        raise TypeError("outcome must be TargetRunOutcome")
    if outcome.status not in _TARGET_TERMINAL:
        raise ValueError("outcome status must be terminal")
    for field in ("read_count", "insert_count", "duplicate_count", "skipped_count"):
        value = getattr(outcome, field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a nonnegative integer")
    _optional_text(outcome.error_code, "error_code", 100)
    _optional_text(outcome.error_summary, "error_summary", 1000)
    _optional_text(outcome.screenshot_path, "screenshot_path", 1000)


def _is_schedule_duplicate(error: IntegrityError) -> bool:
    original = error.orig
    arguments = getattr(original, "args", ())
    return (
        len(arguments) >= 2
        and arguments[0] == 1062
        and "uk_job_schedule" in str(arguments[1])
    )


def _outcome_matches(row, expected: dict[str, object]) -> bool:
    return all(
        row.get(field) == expected[field]
        for field in (
            "status",
            "read_count",
            "insert_count",
            "duplicate_count",
            "skipped_count",
            "error_code",
            "error_summary",
            "screenshot_path",
        )
    )


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _optional_text(value: object, field: str, maximum: int) -> None:
    if value is None:
        return
    _required_text(value, field, maximum)


def _shanghai_datetime(value: object, field: str) -> None:
    ensure_schedule_datetime(value, field_name=field)


def _db_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database datetime value must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


def _to_db_datetime(value: datetime) -> datetime:
    _shanghai_datetime(value, "datetime")
    return value.replace(tzinfo=None)


def _db_time(value: Any) -> time:
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError("database time must be naive")
        return value
    if isinstance(value, timedelta):
        total = value.days * 86_400 + value.seconds
        if value.microseconds or not 0 <= total < 86_400:
            raise ValueError("database time must be within one day")
        hour, remainder = divmod(total, 3_600)
        minute, second = divmod(remainder, 60)
        return time(hour, minute, second)
    if isinstance(value, str):
        parsed = time.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError("database time must be naive")
        return parsed
    raise TypeError("database time value is invalid")


_LOCK_NEXT_DUE = text(
    """
    SELECT
        id AS job_id, job_name, pipeline_type, effective_start_at,
        effective_end_at, daily_window_start, daily_window_end,
        interval_seconds, next_run_at,
        (SELECT COUNT(*) FROM wechat_collection_job_target target
         WHERE target.job_id = wechat_collection_job.id) AS target_total_count
    FROM wechat_collection_job
    WHERE status IN ('scheduled', 'active')
      AND next_run_at <= :now
      AND NOT EXISTS (
          SELECT 1 FROM wechat_collection_job_run active_run
          WHERE active_run.job_id = wechat_collection_job.id
            AND active_run.status IN ('queued', 'running')
      )
    ORDER BY CASE WHEN pipeline_type = 'group' THEN 0 ELSE 1 END,
             next_run_at ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
    """
)

_INSERT_RUN = text(
    """
    INSERT INTO wechat_collection_job_run (
        job_id, scheduled_at, status, worker_id, lease_expires_at,
        start_time, target_total_count
    ) VALUES (
        :job_id, :scheduled_at, 'running', :worker_id, :lease_expires_at,
        :now, :target_total_count
    ) /* uk_job_schedule makes the fixed-grid claim idempotent */
    """
)

_SELECT_TARGET_SNAPSHOTS = text(
    """
    SELECT
        id AS job_target_id,
        COALESCE(group_config_id, article_config_id) AS source_id,
        target_name_snapshot AS source_name,
        priority_snapshot AS priority,
        config_snapshot_json
    FROM wechat_collection_job_target
    WHERE job_id = :job_id
    ORDER BY priority_snapshot ASC, target_name_snapshot ASC, id ASC
    """
)

_INSERT_TARGET_RUN = text(
    """
    INSERT INTO wechat_collection_job_target_run (
        run_id, job_target_id, status
    ) VALUES (:run_id, :job_target_id, 'queued')
    """
)

_ADVANCE_JOB = text(
    """
    UPDATE wechat_collection_job
    SET status = 'active', next_run_at = :next_run_at,
        version = version + 1
    WHERE id = :job_id
      AND status IN ('scheduled', 'active')
    """
)

_COMPLETE_JOB = text(
    """
    UPDATE wechat_collection_job
    SET status = 'completed', next_run_at = NULL,
        version = version + 1
    WHERE id = :job_id
      AND status IN ('scheduled', 'active')
    """
)

_INSERT_MISFIRE_EVENT = text(
    """
    INSERT INTO wechat_collection_job_event (
        job_id, run_id, worker_id, level, event_type, message,
        metrics_json, actor_type, actor_name
    ) VALUES (
        :job_id, :run_id, :worker_id, 'warning', :event_type, :message,
        :metrics_json, 'worker', :worker_id
    )
    """
)

_HEARTBEAT_RUN = text(
    """
    UPDATE wechat_collection_job_run
    SET lease_expires_at = :lease_expires_at
    WHERE id = :run_id
      AND worker_id = :worker_id
      AND status = 'running'
    """
)

_IS_STOP_REQUESTED = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM wechat_collection_job
        WHERE id = :job_id AND status = 'stop_requested'
        LIMIT 1
    )
    """
)

_START_TARGET = text(
    """
    UPDATE wechat_collection_job_target_run target_run
    INNER JOIN wechat_collection_job_run run ON run.id = target_run.run_id
    SET target_run.status = 'running', target_run.batch_id = :batch_id,
        target_run.start_time = :now
    WHERE target_run.run_id = :run_id
      AND target_run.job_target_id = :job_target_id
      AND target_run.status = 'queued'
      AND run.status = 'running'
    """
)

_GET_TARGET_RUN_ID = text(
    """
    SELECT id FROM wechat_collection_job_target_run
    WHERE run_id = :run_id AND job_target_id = :job_target_id
    """
)

_FINISH_TARGET = text(
    """
    UPDATE wechat_collection_job_target_run
    SET status = :status, read_count = :read_count,
        insert_count = :insert_count, duplicate_count = :duplicate_count,
        skipped_count = :skipped_count, error_code = :error_code,
        error_summary = :error_summary, screenshot_path = :screenshot_path,
        end_time = :now
    WHERE id = :target_run_id AND status = 'running'
    """
)

_GET_TARGET_OUTCOME = text(
    """
    SELECT
        status, read_count, insert_count, duplicate_count, skipped_count,
        error_code, error_summary, screenshot_path
    FROM wechat_collection_job_target_run
    WHERE id = :target_run_id
    """
)

_FINISH_RUN = text(
    """
    UPDATE wechat_collection_job_run run
    SET status = :status, end_time = :now, lease_expires_at = NULL,
        target_success_count = (
            SELECT COUNT(*) FROM wechat_collection_job_target_run target
            WHERE target.run_id = run.id AND target.status = 'success'
        ),
        target_failed_count = (
            SELECT COUNT(*) FROM wechat_collection_job_target_run target
            WHERE target.run_id = run.id
              AND target.status IN ('failed', 'cancelled')
        )
    WHERE run.id = :run_id AND run.status = 'running'
      AND NOT EXISTS (
          SELECT 1 FROM wechat_collection_job_target_run unfinished
          WHERE unfinished.run_id = run.id
            AND unfinished.status IN ('queued', 'running')
      )
    """
)

_GET_RUN_STATUS = text(
    """
    SELECT status
    FROM wechat_collection_job_run
    WHERE id = :run_id
    """
)

_SET_STOPPED_AFTER_RUN = text(
    """
    UPDATE wechat_collection_job job
    INNER JOIN wechat_collection_job_run run ON run.job_id = job.id
    SET job.status = 'stopped', job.next_run_at = NULL,
        job.version = job.version + 1
    WHERE run.id = :run_id AND job.status = 'stop_requested'
    """
)

_LOCK_EXPIRED_RUNS = text(
    """
    SELECT id AS run_id, job_id, worker_id
    FROM wechat_collection_job_run
    WHERE status = 'running' AND lease_expires_at <= :now
    ORDER BY lease_expires_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
    """
)

_INSERT_RECOVERY_EVENT = text(
    """
    INSERT INTO wechat_collection_job_event (
        job_id, run_id, worker_id, level, event_type, message,
        metrics_json, actor_type, actor_name
    ) VALUES (
        :job_id, :run_id, :worker_id, 'error', :event_type, :message,
        '{}', 'system', 'runtime-recovery'
    )
    """
)
