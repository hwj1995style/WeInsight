from __future__ import annotations

from datetime import datetime, timedelta

from app.pipelines.article_core_group_due_provider import ReadOnlyCoreGroupDueProvider


class FakeGroupConfigRepo:
    def __init__(self, due_groups) -> None:
        self.due_groups = due_groups
        self.calls: list[tuple[datetime, int]] = []

    def list_due_groups(self, now: datetime, limit: int):
        self.calls.append((now, limit))
        return self.due_groups


def test_read_only_core_group_due_provider_returns_now_when_core_group_due() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    repo = FakeGroupConfigRepo(due_groups=[object()])
    provider = ReadOnlyCoreGroupDueProvider(
        group_config_repo=repo,
        poll_interval_seconds=30,
        now_provider=lambda: now,
    )

    assert provider() == now
    assert repo.calls == [(now, 1)]


def test_read_only_core_group_due_provider_returns_next_poll_when_no_group_due() -> None:
    now = datetime(2026, 7, 6, 9, 0)
    repo = FakeGroupConfigRepo(due_groups=[])
    provider = ReadOnlyCoreGroupDueProvider(
        group_config_repo=repo,
        poll_interval_seconds=30,
        now_provider=lambda: now,
    )

    assert provider() == now + timedelta(seconds=30)
    assert repo.calls == [(now, 1)]
