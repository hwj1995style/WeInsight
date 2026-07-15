from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo


APPLICATION_TIMEZONE = "Asia/Shanghai"
_MAX_GENERATED_BY_LENGTH = 100


class ReportStatus(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"


class GenerationTrigger(str, Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    COMPENSATION = "compensation"
    LEGACY = "legacy"


@dataclass(frozen=True)
class ReportLifecycle:
    report_status: ReportStatus
    data_cutoff_time: datetime
    generation_trigger: GenerationTrigger
    last_generated_by: str

    def __post_init__(self) -> None:
        if not isinstance(self.report_status, ReportStatus):
            raise ValueError("report_status must be a ReportStatus")
        if not isinstance(self.generation_trigger, GenerationTrigger):
            raise ValueError("generation_trigger must be a GenerationTrigger")
        _require_shanghai_datetime(self.data_cutoff_time)
        generated_by = _normalize_generated_by(self.last_generated_by)
        if (
            self.report_status is ReportStatus.PROVISIONAL
            and self.generation_trigger is not GenerationTrigger.MANUAL
        ):
            raise ValueError("provisional report generation_trigger must be manual")
        object.__setattr__(self, "last_generated_by", generated_by)

    @classmethod
    def provisional(cls, cutoff: datetime, generated_by: str) -> "ReportLifecycle":
        return cls(
            ReportStatus.PROVISIONAL,
            cutoff,
            GenerationTrigger.MANUAL,
            generated_by,
        )

    @classmethod
    def final(
        cls,
        cutoff: datetime,
        trigger: GenerationTrigger,
        generated_by: str,
    ) -> "ReportLifecycle":
        return cls(ReportStatus.FINAL, cutoff, trigger, generated_by)

    @classmethod
    def manual_for_date(
        cls,
        report_date: date,
        now: datetime,
        generated_by: str,
    ) -> "ReportLifecycle":
        _require_shanghai_datetime(now)
        if not isinstance(report_date, date) or isinstance(report_date, datetime):
            raise ValueError("report_date must be a calendar date")
        if report_date > now.date():
            raise ValueError("future report date is not allowed")
        if report_date == now.date():
            return cls.provisional(now, generated_by)
        return cls.final(now, GenerationTrigger.MANUAL, generated_by)


def _require_shanghai_datetime(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != APPLICATION_TIMEZONE
    ):
        raise ValueError(
            f"data_cutoff_time must use {APPLICATION_TIMEZONE} ZoneInfo"
        )


def _normalize_generated_by(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("generated_by must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("generated_by must not be empty")
    if len(normalized) > _MAX_GENERATED_BY_LENGTH:
        raise ValueError(
            f"generated_by must be at most {_MAX_GENERATED_BY_LENGTH} characters"
        )
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("generated_by must not contain control characters")
    return normalized
