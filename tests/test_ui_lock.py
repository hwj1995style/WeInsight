from __future__ import annotations

from datetime import datetime, timedelta

from app.storage.lock_repo import InMemoryUiLockRepo


def test_lock_acquire_and_release() -> None:
    repo = InMemoryUiLockRepo()
    now = datetime(2026, 7, 2, 8, 0, 0)

    acquired = repo.acquire(
        lock_name="wechat_ui",
        owner_pipeline="group",
        owner_task_id="group-1",
        now=now,
        lease_seconds=120,
    )

    assert acquired is True
    assert repo.current_owner("wechat_ui") == "group"

    repo.release("wechat_ui", owner_pipeline="group", owner_task_id="group-1")
    assert repo.current_owner("wechat_ui") is None


def test_stale_lock_can_be_recovered() -> None:
    repo = InMemoryUiLockRepo()
    now = datetime(2026, 7, 2, 8, 0, 0)

    assert repo.acquire("wechat_ui", "article", "article-1", now, 60) is True
    recovered = repo.recover_stale(
        lock_name="wechat_ui",
        recovered_by="group-scheduler",
        now=now + timedelta(seconds=181),
        stale_after_seconds=180,
    )

    assert recovered is True
    assert repo.current_owner("wechat_ui") is None
    assert repo.stale_lock_recovered_count == 1


def test_current_owner_treats_equal_expiry_as_expired_without_deleting() -> None:
    repo = InMemoryUiLockRepo()
    acquired_at = datetime(2026, 7, 10, 9, 0, 0)
    assert repo.acquire("wechat_ui", "group", "task-1", acquired_at, 120)
    expires_at = acquired_at + timedelta(seconds=120)

    assert (
        repo.current_owner("wechat_ui", expires_at - timedelta(microseconds=1))
        == "group"
    )
    assert repo.current_owner("wechat_ui", expires_at) is None
    assert repo.current_owner("wechat_ui") == "group"
