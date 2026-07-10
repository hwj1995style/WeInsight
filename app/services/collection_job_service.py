from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Protocol

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    JobStatus,
    PipelineType,
    ScheduleSpec,
    ensure_schedule_datetime,
)
from app.services.collection_schedule import next_run_at


@dataclass(frozen=True, slots=True)
class CreateCollectionJobCommand:
    job_name: str
    pipeline_type: PipelineType
    target_ids: tuple[int, ...]
    effective_start_at: datetime
    effective_end_at: datetime
    daily_window_start: time
    daily_window_end: time
    interval_seconds: int


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    source_id: int
    source_name: str
    priority: int
    config_json: str


@dataclass(frozen=True, slots=True)
class JobListFilter:
    pipeline_type: PipelineType | None = None
    status: JobStatus | None = None
    name_contains: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionJobSummary:
    id: int
    job_name: str
    pipeline_type: PipelineType
    status: JobStatus
    next_run_at: datetime | None
    target_count: int
    version: int


@dataclass(frozen=True, slots=True)
class CollectionJobDetail:
    id: int
    job_name: str
    pipeline_type: PipelineType
    target_names: tuple[str, ...]
    schedule: ScheduleSpec
    status: JobStatus
    next_run_at: datetime | None
    version: int


class JobValidationError(ValueError):
    pass


class JobOverlapError(RuntimeError):
    def __init__(self, job_names: list[str] | tuple[str, ...]) -> None:
        self.job_names = tuple(dict.fromkeys(job_names))
        super().__init__("targets overlap existing collection jobs")


class JobTargetNotFoundError(LookupError):
    pass


class JobTargetDisabledError(RuntimeError):
    pass


class JobMixedPipelineError(RuntimeError):
    pass


class JobNotFoundError(LookupError):
    pass


class JobVersionConflictError(RuntimeError):
    pass


class JobStateTransitionError(RuntimeError):
    def __init__(self, status: JobStatus, action: str) -> None:
        self.status = status
        self.action = action
        super().__init__(f"cannot {action} job in {status.value} status")


class CollectionJobRepo(Protocol):
    def create_job(
        self,
        command: CreateCollectionJobCommand,
        status: JobStatus,
        next_run_at: datetime,
        actor: str,
    ) -> int: ...

    def request_stop(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> JobStatus: ...

    def soft_delete(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> bool: ...

    def list_jobs(
        self,
        filters: JobListFilter,
        page: int,
        page_size: int,
    ) -> PagedResult[CollectionJobSummary]: ...

    def get_job(self, job_id: int) -> CollectionJobDetail | None: ...


class CollectionJobService:
    def __init__(self, repo: CollectionJobRepo) -> None:
        self.repo = repo

    def create_job(
        self,
        command: CreateCollectionJobCommand,
        actor: str,
        now: datetime,
    ) -> int:
        self._validate_actor(actor)
        self._validate_now(now)
        normalized, schedule = self._validated_create_command(command)
        inclusive_after = now - timedelta(microseconds=1)
        scheduled_at = next_run_at(
            schedule,
            after=inclusive_after,
            anchor=schedule.effective_start_at,
        )
        if scheduled_at is None:
            raise JobValidationError("schedule has no future run")
        status = (
            JobStatus.SCHEDULED
            if now < schedule.effective_start_at
            else JobStatus.ACTIVE
        )
        return self.repo.create_job(
            normalized,
            status,
            scheduled_at,
            actor,
        )

    def request_stop(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> JobStatus:
        self._validate_identity(job_id, "job_id")
        self._validate_identity(expected_version, "expected_version")
        self._validate_actor(actor)
        self._validate_now(now)
        return self.repo.request_stop(job_id, expected_version, actor, now)

    def delete_job(
        self,
        job_id: int,
        expected_version: int,
        actor: str,
        now: datetime,
    ) -> bool:
        self._validate_identity(job_id, "job_id")
        self._validate_identity(expected_version, "expected_version")
        self._validate_actor(actor)
        self._validate_now(now)
        return self.repo.soft_delete(job_id, expected_version, actor, now)

    def list_jobs(
        self,
        filters: JobListFilter,
        page: int,
        page_size: int,
    ) -> PagedResult[CollectionJobSummary]:
        self._validate_filters(filters)
        self._validate_identity(page, "page")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 100
        ):
            raise JobValidationError("page_size must be between 1 and 100")
        return self.repo.list_jobs(filters, page, page_size)

    def get_job(self, job_id: int) -> CollectionJobDetail:
        self._validate_identity(job_id, "job_id")
        detail = self.repo.get_job(job_id)
        if detail is None:
            raise JobNotFoundError(f"collection job not found: {job_id}")
        return detail

    @classmethod
    def _validated_create_command(
        cls, command: CreateCollectionJobCommand
    ) -> tuple[CreateCollectionJobCommand, ScheduleSpec]:
        if not isinstance(command, CreateCollectionJobCommand):
            raise JobValidationError("command must be CreateCollectionJobCommand")
        cls._validate_name(command.job_name, "job_name", maximum=200)
        if not isinstance(command.pipeline_type, PipelineType):
            raise JobValidationError("pipeline_type must be group or article")
        if not isinstance(command.target_ids, tuple) or not command.target_ids:
            raise JobValidationError("at least one target is required")
        for source_id in command.target_ids:
            cls._validate_identity(source_id, "target_id")
        minimum = 30 if command.pipeline_type is PipelineType.GROUP else 600
        if (
            isinstance(command.interval_seconds, bool)
            or not isinstance(command.interval_seconds, int)
            or command.interval_seconds < minimum
        ):
            raise JobValidationError(
                f"interval_seconds must be at least {minimum}"
            )
        try:
            schedule = ScheduleSpec(
                effective_start_at=command.effective_start_at,
                effective_end_at=command.effective_end_at,
                daily_window_start=command.daily_window_start,
                daily_window_end=command.daily_window_end,
                interval_seconds=command.interval_seconds,
                timezone=APPLICATION_TIMEZONE,
            )
        except (TypeError, ValueError) as exc:
            raise JobValidationError(str(exc)) from exc
        target_ids = tuple(sorted(set(command.target_ids)))
        return replace(command, target_ids=target_ids), schedule

    @classmethod
    def _validate_filters(cls, filters: JobListFilter) -> None:
        if not isinstance(filters, JobListFilter):
            raise JobValidationError("filters must be JobListFilter")
        if filters.pipeline_type is not None and not isinstance(
            filters.pipeline_type, PipelineType
        ):
            raise JobValidationError("pipeline_type must be group or article")
        if filters.status is not None and not isinstance(filters.status, JobStatus):
            raise JobValidationError("status must be a JobStatus")
        if filters.name_contains is not None:
            if not isinstance(filters.name_contains, str):
                raise JobValidationError("name_contains must be a string")
            if len(filters.name_contains) > 200:
                raise JobValidationError(
                    "name_contains must be at most 200 characters"
                )

    @staticmethod
    def _validate_identity(value: object, field: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise JobValidationError(f"{field} must be a positive integer")

    @classmethod
    def _validate_actor(cls, actor: object) -> None:
        cls._validate_name(actor, "actor", maximum=100)

    @staticmethod
    def _validate_name(value: object, field: str, *, maximum: int) -> None:
        if not isinstance(value, str) or not value:
            raise JobValidationError(f"{field} must not be empty")
        if value != value.strip():
            raise JobValidationError(f"{field} must not have surrounding whitespace")
        if len(value) > maximum:
            raise JobValidationError(f"{field} must be at most {maximum} characters")

    @staticmethod
    def _validate_now(now: object) -> None:
        try:
            ensure_schedule_datetime(now, field_name="now")
        except (TypeError, ValueError) as exc:
            raise JobValidationError(str(exc)) from exc
