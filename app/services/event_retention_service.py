from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.collection_jobs import ensure_schedule_datetime


@dataclass(frozen=True, slots=True)
class EventRetentionPolicy:
    info_days: int = 14
    verbose_days: int = 7
    warning_error_months: int = 3
    audit_months: int = 6
    batch_size: int = 1000
    max_batches: int = 20


@dataclass(frozen=True, slots=True)
class EventCleanupResult:
    acquired: bool
    dry_run: bool
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class EventRetentionRepo(Protocol):
    def cleanup(self, now: datetime, policy: EventRetentionPolicy, *, dry_run: bool) -> EventCleanupResult: ...


class EventRetentionService:
    def __init__(self, repo: EventRetentionRepo, policy: EventRetentionPolicy) -> None:
        self.repo = repo
        self.policy = policy

    def run(self, now: datetime, *, dry_run: bool = False) -> EventCleanupResult:
        ensure_schedule_datetime(now, field_name="now")
        return self.repo.cleanup(now, self.policy, dry_run=dry_run)
