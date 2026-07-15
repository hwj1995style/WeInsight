from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CollectionOutcomeCounts:
    success: int
    failed: int
    skipped: int
    total: int

    def __post_init__(self) -> None:
        values = (self.success, self.failed, self.skipped, self.total)
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("collection counts must be non-negative integers")
        if self.success + self.failed + self.skipped != self.total:
            raise ValueError("success + failed + skipped must equal total")


@dataclass(frozen=True)
class BacklogCount:
    pipeline: str
    task_type: str
    status: str
    count: int

    def __post_init__(self) -> None:
        if self.pipeline not in {"group", "article"}:
            raise ValueError("unsupported backlog pipeline")
        if not self.task_type or not self.status:
            raise ValueError("backlog labels must not be empty")
        if not isinstance(self.count, int) or self.count < 0:
            raise ValueError("backlog count must be a non-negative integer")


@dataclass(frozen=True)
class DashboardSnapshot:
    window_hours: int
    group_collection: CollectionOutcomeCounts
    article_collection: CollectionOutcomeCounts
    group_config_total: int
    group_config_enabled: int
    article_config_total: int
    article_config_enabled: int
    group_daily_report_count: int
    article_daily_report_count: int
    backlogs: tuple[BacklogCount, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.window_hours, int) or self.window_hours < 1:
            raise ValueError("window_hours must be a positive integer")
        counts = (
            self.group_config_total,
            self.group_config_enabled,
            self.article_config_total,
            self.article_config_enabled,
            self.group_daily_report_count,
            self.article_daily_report_count,
        )
        if any(not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("dashboard counts must be non-negative integers")
        if self.group_config_enabled > self.group_config_total:
            raise ValueError("enabled group config count exceeds total")
        if self.article_config_enabled > self.article_config_total:
            raise ValueError("enabled article config count exceeds total")

    @property
    def daily_report_count(self) -> int:
        return self.group_daily_report_count + self.article_daily_report_count

    @property
    def backlog_count(self) -> int:
        return sum(item.count for item in self.backlogs)

    @classmethod
    def empty(cls, *, window_hours: int) -> "DashboardSnapshot":
        zero = CollectionOutcomeCounts(success=0, failed=0, skipped=0, total=0)
        return cls(
            window_hours=window_hours,
            group_collection=zero,
            article_collection=zero,
            group_config_total=0,
            group_config_enabled=0,
            article_config_total=0,
            article_config_enabled=0,
            group_daily_report_count=0,
            article_daily_report_count=0,
            backlogs=(),
        )


class DashboardRepo(Protocol):
    def get_snapshot(self, hours: int) -> DashboardSnapshot: ...


class DashboardService:
    def __init__(self, repo: DashboardRepo) -> None:
        self.repo = repo

    def get_snapshot(self, hours: int = 24) -> DashboardSnapshot:
        if not isinstance(hours, int) or isinstance(hours, bool) or hours < 1:
            raise ValueError("hours must be a positive integer")
        return self.repo.get_snapshot(hours)
