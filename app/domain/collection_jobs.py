from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APPLICATION_TIMEZONE = "Asia/Shanghai"


class PipelineType(str, Enum):
    GROUP = "group"
    ARTICLE = "article"


class JobStatus(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"
    COMPLETED = "completed"
    DELETED = "deleted"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


def ensure_schedule_datetime(value: object, *, field_name: str) -> None:
    """Validate the one timezone contract used by persisted collection schedules."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if (
        not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != APPLICATION_TIMEZONE
    ):
        raise ValueError(
            f"{field_name} must use {APPLICATION_TIMEZONE} ZoneInfo"
        )


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    effective_start_at: datetime
    effective_end_at: datetime
    daily_window_start: time
    daily_window_end: time
    interval_seconds: int
    timezone: str = APPLICATION_TIMEZONE

    def __post_init__(self) -> None:
        try:
            configured_zone = ZoneInfo(self.timezone)
        except (TypeError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        if configured_zone.key != APPLICATION_TIMEZONE:
            raise ValueError(f"timezone must be {APPLICATION_TIMEZONE}")

        ensure_schedule_datetime(
            self.effective_start_at,
            field_name="effective_start_at",
        )
        ensure_schedule_datetime(
            self.effective_end_at,
            field_name="effective_end_at",
        )
        if self.effective_start_at >= self.effective_end_at:
            raise ValueError("effective_start_at must be before effective_end_at")

        if not isinstance(self.daily_window_start, time):
            raise TypeError("daily_window_start must be a time")
        if not isinstance(self.daily_window_end, time):
            raise TypeError("daily_window_end must be a time")
        if self.daily_window_start.tzinfo is not None:
            raise ValueError("daily_window_start must not include tzinfo")
        if self.daily_window_end.tzinfo is not None:
            raise ValueError("daily_window_end must not include tzinfo")

        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, int)
            or self.interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a positive integer")
