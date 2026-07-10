from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class CoreGroupDueReadRepo(Protocol):
    def list_due_groups(self, now: datetime, limit: int):
        ...


@dataclass(frozen=True)
class ReadOnlyCoreGroupDueProvider:
    group_config_repo: CoreGroupDueReadRepo
    poll_interval_seconds: int
    now_provider: Callable[[], datetime] = datetime.now

    def __call__(self) -> datetime:
        now = self.now_provider()
        due_groups = self.group_config_repo.list_due_groups(now, 1)
        if due_groups:
            return now
        return now + timedelta(seconds=self.poll_interval_seconds)
