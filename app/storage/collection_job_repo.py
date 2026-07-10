from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    JobStatus,
    PipelineType,
    ScheduleSpec,
)
from app.services.collection_job_service import (
    CollectionJobDetail,
    CollectionJobSummary,
    CreateCollectionJobCommand,
    JobListFilter,
    JobMixedPipelineError,
    JobNotFoundError,
    JobOverlapError,
    JobStateTransitionError,
    JobTargetDisabledError,
    JobTargetNotFoundError,
    JobVersionConflictError,
    SourceSnapshot,
)
from app.services.collection_schedule import schedules_overlap
from app.storage.source_mutation_repo import (
    MysqlSourceWriteGuard,
    SourceGuardDisabledError,
    SourceGuardNotFoundError,
)


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_ACTIVE_OVERLAP_STATUSES = (
    JobStatus.SCHEDULED,
    JobStatus.ACTIVE,
    JobStatus.STOP_REQUESTED,
)


class MysqlCollectionJobRepo:
    def __init__(
        self,
        engine: Engine,
        source_guard: MysqlSourceWriteGuard | None = None,
    ) -> None:
        self.engine = engine
        self.source_guard = source_guard or MysqlSourceWriteGuard()

    def create_job(
        self,
        command: CreateCollectionJobCommand,
        status: JobStatus,
        next_run_at: datetime,
        actor: str,
    ) -> int:
        """Atomically lock targets, detect overlap, and persist one job."""
        source_type = command.pipeline_type.value
        target_ids = tuple(sorted(set(command.target_ids)))
        requested_schedule = _schedule_from_command(command)

        with self.engine.begin() as connection:
            snapshots = [
                self._lock_source_snapshot(
                    connection,
                    source_type,
                    source_id,
                )
                for source_id in target_ids
            ]
            overlap_names = self._list_overlapping_jobs_on_connection(
                connection,
                command.pipeline_type,
                target_ids,
                requested_schedule,
            )
            if overlap_names:
                raise JobOverlapError(overlap_names)

            result = connection.execute(
                _INSERT_JOB,
                {
                    "job_name": command.job_name,
                    "pipeline_type": command.pipeline_type.value,
                    "effective_start_at": _to_db_datetime(
                        command.effective_start_at
                    ),
                    "effective_end_at": _to_db_datetime(command.effective_end_at),
                    "daily_window_start": command.daily_window_start,
                    "daily_window_end": command.daily_window_end,
                    "interval_seconds": command.interval_seconds,
                    "status": status.value,
                    "next_run_at": _to_db_datetime(next_run_at),
                },
            )
            job_id = int(result.lastrowid)
            ordered_snapshots = sorted(
                snapshots,
                key=lambda item: (item.priority, item.source_name, item.source_id),
            )
            connection.execute(
                _INSERT_TARGET,
                [
                    {
                        "job_id": job_id,
                        "source_id": snapshot.source_id,
                        "group_config_id": (
                            snapshot.source_id
                            if command.pipeline_type is PipelineType.GROUP
                            else None
                        ),
                        "article_config_id": (
                            snapshot.source_id
                            if command.pipeline_type is PipelineType.ARTICLE
                            else None
                        ),
                        "target_name_snapshot": snapshot.source_name,
                        "priority_snapshot": snapshot.priority,
                        "config_snapshot_json": snapshot.config_json,
                    }
                    for snapshot in ordered_snapshots
                ],
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="job_created",
                message="collection job created",
                actor=actor,
            )
            return job_id

    def list_overlapping_jobs(
        self,
        pipeline_type: PipelineType,
        target_ids: tuple[int, ...],
        schedule: ScheduleSpec,
    ) -> list[str]:
        """Read-only hint; create_job performs the authoritative locked check."""
        with self.engine.begin() as connection:
            return self._list_overlapping_jobs_on_connection(
                connection,
                pipeline_type,
                tuple(sorted(set(target_ids))),
                schedule,
            )

    def get_job(self, job_id: int) -> CollectionJobDetail | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                _GET_JOB,
                {"job_id": job_id},
            ).mappings().first()
            if row is None:
                return None
            targets = connection.execute(
                _GET_JOB_TARGET_NAMES,
                {"job_id": job_id},
            ).mappings().all()
        return CollectionJobDetail(
            id=int(row["id"]),
            job_name=str(row["job_name"]),
            pipeline_type=PipelineType(str(row["pipeline_type"])),
            target_names=tuple(str(item["target_name_snapshot"]) for item in targets),
            schedule=_schedule_from_row(row),
            status=JobStatus(str(row["status"])),
            next_run_at=_optional_db_datetime(row.get("next_run_at")),
            version=int(row["version"]),
        )

    def list_jobs(
        self,
        filters: JobListFilter,
        page: int,
        page_size: int,
    ) -> PagedResult[CollectionJobSummary]:
        where_sql, filter_params = _list_filter_clause(filters)
        count_statement = text(
            f"""
            SELECT COUNT(*)
            FROM wechat_collection_job
            {where_sql}
            """
        )
        data_statement = text(
            f"""
            SELECT
                id,
                job_name,
                pipeline_type,
                status,
                next_run_at,
                (
                    SELECT COUNT(*)
                    FROM wechat_collection_job_target target
                    WHERE target.job_id = wechat_collection_job.id
                ) AS target_count,
                version
            FROM wechat_collection_job
            {where_sql}
            ORDER BY update_time DESC, id DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
        data_params = {
            **filter_params,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        with self.engine.begin() as connection:
            total_count = int(
                connection.execute(count_statement, filter_params).scalar_one()
            )
            rows = connection.execute(
                data_statement,
                data_params,
            ).mappings().all()
        return PagedResult(
            items=[_summary_from_row(row) for row in rows],
            page=page,
            page_size=page_size,
            total_count=total_count,
        )

    def request_stop(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> JobStatus:
        with self.engine.begin() as connection:
            row = self._lock_job(connection, job_id)
            current = JobStatus(str(row["status"]))
            if current in {JobStatus.STOP_REQUESTED, JobStatus.STOPPED}:
                return current
            if current is JobStatus.SCHEDULED:
                target = JobStatus.STOPPED
            elif current is JobStatus.ACTIVE:
                target = JobStatus.STOP_REQUESTED
            else:
                raise JobStateTransitionError(current, "stop")
            if int(row["version"]) != expected_version:
                raise JobVersionConflictError(
                    f"collection job version conflict: {job_id}"
                )
            result = connection.execute(
                _REQUEST_STOP,
                {
                    "job_id": job_id,
                    "expected_version": expected_version,
                    "status": target.value,
                    "now": _to_db_datetime(now),
                    "actor": actor,
                },
            )
            if int(result.rowcount or 0) != 1:
                raise JobVersionConflictError(
                    f"collection job version conflict: {job_id}"
                )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="job_stop_requested",
                message=f"collection job moved to {target.value}",
                actor=actor,
            )
            return target

    def soft_delete(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> bool:
        with self.engine.begin() as connection:
            row = self._lock_job(connection, job_id)
            current = JobStatus(str(row["status"]))
            if current is JobStatus.DELETED:
                return True
            if current not in {JobStatus.STOPPED, JobStatus.COMPLETED}:
                raise JobStateTransitionError(current, "delete")
            if int(row["version"]) != expected_version:
                raise JobVersionConflictError(
                    f"collection job version conflict: {job_id}"
                )
            result = connection.execute(
                _SOFT_DELETE,
                {
                    "job_id": job_id,
                    "expected_version": expected_version,
                    "deleted_at": _to_db_datetime(now),
                    "actor": actor,
                },
            )
            if int(result.rowcount or 0) != 1:
                raise JobVersionConflictError(
                    f"collection job version conflict: {job_id}"
                )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="job_deleted",
                message="collection job soft deleted",
                actor=actor,
            )
            return True

    def _lock_source_snapshot(
        self,
        connection: Connection,
        source_type: str,
        source_id: int,
    ) -> SourceSnapshot:
        try:
            record = self.source_guard.lock_for_job_creation(
                connection,
                source_type,
                source_id,
            )
        except SourceGuardDisabledError as exc:
            raise JobTargetDisabledError(str(exc)) from exc
        except SourceGuardNotFoundError as exc:
            if self._source_exists_in_other_pipeline(
                connection,
                source_type,
                source_id,
            ):
                raise JobMixedPipelineError(
                    "all targets must belong to the same pipeline"
                ) from exc
            raise JobTargetNotFoundError(str(exc)) from exc
        return SourceSnapshot(
            source_id=record.id,
            source_name=record.source_name,
            priority=record.priority,
            config_json=json.dumps(
                record.config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=_json_default,
            ),
        )

    @staticmethod
    def _source_exists_in_other_pipeline(
        connection: Connection,
        source_type: str,
        source_id: int,
    ) -> bool:
        table = (
            "wechat_public_account_config"
            if source_type == PipelineType.GROUP.value
            else "wechat_group_config"
        )
        row = connection.execute(
            text(
                f"""
                SELECT id
                FROM {table}
                WHERE id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().first()
        return row is not None

    @staticmethod
    def _list_overlapping_jobs_on_connection(
        connection: Connection,
        pipeline_type: PipelineType,
        target_ids: tuple[int, ...],
        schedule: ScheduleSpec,
    ) -> list[str]:
        if not target_ids:
            return []
        target_column = (
            "group_config_id"
            if pipeline_type is PipelineType.GROUP
            else "article_config_id"
        )
        placeholders = ", ".join(
            f":target_id_{index}" for index in range(len(target_ids))
        )
        params: dict[str, Any] = {"pipeline_type": pipeline_type.value}
        params.update(
            {
                f"target_id_{index}": source_id
                for index, source_id in enumerate(target_ids)
            }
        )
        rows = connection.execute(
            text(
                f"""
                SELECT DISTINCT
                    job.id,
                    job.job_name,
                    job.effective_start_at,
                    job.effective_end_at,
                    job.daily_window_start,
                    job.daily_window_end,
                    job.interval_seconds
                FROM wechat_collection_job job
                INNER JOIN wechat_collection_job_target target
                    ON target.job_id = job.id
                WHERE job.pipeline_type = :pipeline_type
                  AND job.status IN ('scheduled', 'active', 'stop_requested')
                  AND target.{target_column} IN ({placeholders})
                ORDER BY job.id ASC
                """
            ),
            params,
        ).mappings().all()
        names: list[str] = []
        for row in rows:
            if schedules_overlap(schedule, _schedule_from_row(row)):
                name = str(row["job_name"])
                if name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _lock_job(connection: Connection, job_id: int):
        row = connection.execute(
            _LOCK_JOB,
            {"job_id": job_id},
        ).mappings().first()
        if row is None:
            raise JobNotFoundError(f"collection job not found: {job_id}")
        return row

    @staticmethod
    def _insert_event(
        connection: Connection,
        *,
        job_id: int,
        event_type: str,
        message: str,
        actor: str,
    ) -> None:
        connection.execute(
            _INSERT_EVENT,
            {
                "job_id": job_id,
                "event_type": event_type,
                "message": message,
                "actor": actor,
            },
        )


def _schedule_from_command(command: CreateCollectionJobCommand) -> ScheduleSpec:
    return ScheduleSpec(
        effective_start_at=command.effective_start_at,
        effective_end_at=command.effective_end_at,
        daily_window_start=command.daily_window_start,
        daily_window_end=command.daily_window_end,
        interval_seconds=command.interval_seconds,
        timezone=APPLICATION_TIMEZONE,
    )


def _schedule_from_row(row) -> ScheduleSpec:
    return ScheduleSpec(
        effective_start_at=_db_datetime(row["effective_start_at"]),
        effective_end_at=_db_datetime(row["effective_end_at"]),
        daily_window_start=_db_time(row["daily_window_start"]),
        daily_window_end=_db_time(row["daily_window_end"]),
        interval_seconds=int(row["interval_seconds"]),
        timezone=APPLICATION_TIMEZONE,
    )


def _summary_from_row(row) -> CollectionJobSummary:
    return CollectionJobSummary(
        id=int(row["id"]),
        job_name=str(row["job_name"]),
        pipeline_type=PipelineType(str(row["pipeline_type"])),
        status=JobStatus(str(row["status"])),
        next_run_at=_optional_db_datetime(row.get("next_run_at")),
        target_count=int(row["target_count"]),
        version=int(row["version"]),
    )


def _db_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database datetime value must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


def _optional_db_datetime(value: Any) -> datetime | None:
    return None if value is None else _db_datetime(value)


def _to_db_datetime(value: datetime) -> datetime:
    return value.astimezone(_ZONE).replace(tzinfo=None)


def _db_time(value: Any) -> time:
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError("database time value must not include tzinfo")
        return value
    if isinstance(value, timedelta):
        total_microseconds = (
            (value.days * 86_400 + value.seconds) * 1_000_000
            + value.microseconds
        )
        if not 0 <= total_microseconds < 86_400 * 1_000_000:
            raise ValueError("database time value must be within one day")
        hour, remainder = divmod(total_microseconds, 3_600 * 1_000_000)
        minute, remainder = divmod(remainder, 60 * 1_000_000)
        second, microsecond = divmod(remainder, 1_000_000)
        return time(
            int(hour),
            int(minute),
            int(second),
            int(microsecond),
        )
    if isinstance(value, str):
        parsed = time.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError("database time value must not include tzinfo")
        return parsed
    raise TypeError("database time value must be time, timedelta, or string")


def _json_default(value: Any) -> str:
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    if isinstance(value, timedelta):
        return _db_time(value).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        return _db_datetime(value).isoformat(timespec="seconds")
    raise TypeError(f"unsupported snapshot value: {type(value).__name__}")


def _list_filter_clause(filters: JobListFilter) -> tuple[str, dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if filters.pipeline_type is not None:
        conditions.append("pipeline_type = :pipeline_type")
        params["pipeline_type"] = filters.pipeline_type.value
    if filters.status is not None:
        conditions.append("status = :status")
        params["status"] = filters.status.value
    else:
        conditions.append("status <> 'deleted'")
    if filters.name_contains is not None:
        conditions.append("job_name LIKE :name_contains ESCAPE '\\\\'")
        escaped = (
            filters.name_contains.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        params["name_contains"] = f"%{escaped}%"
    if filters.date is not None:
        date_start = datetime.combine(filters.date, time.min, tzinfo=_ZONE)
        date_end = date_start + timedelta(days=1)
        conditions.append("effective_start_at < :date_end_exclusive")
        conditions.append("effective_end_at > :date_start_inclusive")
        params["date_start_inclusive"] = _to_db_datetime(date_start)
        params["date_end_exclusive"] = _to_db_datetime(date_end)
    where_sql = "" if not conditions else "WHERE " + " AND ".join(conditions)
    return where_sql, params


_INSERT_JOB = text(
    """
    INSERT INTO wechat_collection_job (
        job_name,
        pipeline_type,
        effective_start_at,
        effective_end_at,
        daily_window_start,
        daily_window_end,
        interval_seconds,
        status,
        next_run_at
    ) VALUES (
        :job_name,
        :pipeline_type,
        :effective_start_at,
        :effective_end_at,
        :daily_window_start,
        :daily_window_end,
        :interval_seconds,
        :status,
        :next_run_at
    )
    """
)


_INSERT_TARGET = text(
    """
    INSERT INTO wechat_collection_job_target (
        job_id,
        group_config_id,
        article_config_id,
        target_name_snapshot,
        priority_snapshot,
        config_snapshot_json
    ) VALUES (
        :job_id,
        :group_config_id,
        :article_config_id,
        :target_name_snapshot,
        :priority_snapshot,
        :config_snapshot_json
    )
    """
)


_INSERT_EVENT = text(
    """
    INSERT INTO wechat_collection_job_event (
        job_id,
        level,
        event_type,
        message,
        actor_type,
        actor_name
    ) VALUES (
        :job_id,
        'info',
        :event_type,
        :message,
        'admin',
        :actor
    )
    """
)


_GET_JOB = text(
    """
    SELECT
        id,
        job_name,
        pipeline_type,
        effective_start_at,
        effective_end_at,
        daily_window_start,
        daily_window_end,
        interval_seconds,
        status,
        next_run_at,
        version
    FROM wechat_collection_job
    WHERE id = :job_id
    """
)


_GET_JOB_TARGET_NAMES = text(
    """
    SELECT target_name_snapshot
    FROM wechat_collection_job_target
    WHERE job_id = :job_id
    ORDER BY priority_snapshot ASC, target_name_snapshot ASC, id ASC
    """
)


_LOCK_JOB = text(
    """
    SELECT status, version
    FROM wechat_collection_job
    WHERE id = :job_id
    FOR UPDATE
    """
)


_REQUEST_STOP = text(
    """
    UPDATE wechat_collection_job
    SET status = :status,
        next_run_at = NULL,
        stop_requested_at = :now,
        stop_requested_by = :actor,
        version = version + 1,
        update_time = CURRENT_TIMESTAMP
    WHERE id = :job_id
      AND version = :expected_version
    """
)


_SOFT_DELETE = text(
    """
    UPDATE wechat_collection_job
    SET status = 'deleted',
        next_run_at = NULL,
        deleted_at = :deleted_at,
        deleted_by = :actor,
        version = version + 1,
        update_time = CURRENT_TIMESTAMP
    WHERE id = :job_id
      AND version = :expected_version
    """
)
