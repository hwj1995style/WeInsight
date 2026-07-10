from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.managed_mode_guard import (
    HeldUiLockAdapter,
    ManagedModeActiveError,
    ManagedModeGuard,
    WechatUiBusyError,
    WechatUiLeaseLostError,
    WechatUiReleaseError,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 18, 0, tzinfo=ZONE)


class HeartbeatRepo:
    def __init__(self, live: bool = False) -> None:
        self.live = live
        self.calls = []

    def has_live_collector(
        self,
        hostname: str,
        now: datetime,
        ttl_seconds: int,
        exclude_worker_id: str | None = None,
    ) -> bool:
        self.calls.append((hostname, now, ttl_seconds, exclude_worker_id))
        return self.live


class UiLockRepo:
    def __init__(
        self,
        *,
        acquire_result: bool = True,
        heartbeat_results=None,
        release_result: bool = True,
    ) -> None:
        self.acquire_result = acquire_result
        self.heartbeat_results = list(heartbeat_results or [True])
        self.release_result = release_result
        self.acquire_calls = []
        self.heartbeat_calls = []
        self.release_calls = []
        self.heartbeat_seen = threading.Event()

    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        self.acquire_calls.append(
            (lock_name, owner_pipeline, owner_task_id, now, lease_seconds)
        )
        return self.acquire_result

    def heartbeat(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
    ) -> bool:
        self.heartbeat_calls.append(
            (lock_name, owner_pipeline, owner_task_id, now)
        )
        self.heartbeat_seen.set()
        if len(self.heartbeat_results) > 1:
            return self.heartbeat_results.pop(0)
        return self.heartbeat_results[0]

    def release(
        self, lock_name: str, owner_pipeline: str, owner_task_id: str
    ) -> bool:
        self.release_calls.append((lock_name, owner_pipeline, owner_task_id))
        return self.release_result


def build_guard(*, live=False, ui_lock_repo=None) -> ManagedModeGuard:
    return ManagedModeGuard(
        heartbeat_repo=HeartbeatRepo(live),
        ui_lock_repo=ui_lock_repo or UiLockRepo(),
        hostname="HOST-A",
        collector_heartbeat_ttl_seconds=30,
        ui_lease_seconds=120,
        ui_heartbeat_interval_seconds=0.01,
        now_provider=lambda: NOW + timedelta(seconds=10),
    )


def test_legacy_scheduler_rejected_when_collector_is_live() -> None:
    guard = build_guard(live=True)

    with pytest.raises(ManagedModeActiveError) as raised:
        guard.ensure_scheduler_allowed(NOW)

    assert str(raised.value) == "managed collector is active"
    assert guard.heartbeat_repo.calls == [("HOST-A", NOW, 30, None)]


@pytest.mark.parametrize("live", [False], ids=["stale-or-excluded-status"])
def test_scheduler_allowed_when_repo_excludes_stale_or_inactive_rows(live) -> None:
    guard = build_guard(live=live)
    guard.ensure_scheduler_allowed(NOW)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 7, 10, 18, 0),
        datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
    ],
)
def test_guard_requires_exact_shanghai_zoneinfo(now) -> None:
    guard = build_guard()
    with pytest.raises(ValueError, match="timezone|Asia/Shanghai"):
        guard.ensure_scheduler_allowed(now)
    with pytest.raises(ValueError, match="timezone|Asia/Shanghai"):
        guard.run_manual("group", "manual-1", now, lambda: None)


@pytest.mark.parametrize("pipeline", ["", "GROUP", "pipeline", None])
def test_manual_rejects_invalid_pipeline(pipeline) -> None:
    with pytest.raises(ValueError, match="pipeline"):
        build_guard().run_manual(pipeline, "manual-1", NOW, lambda: None)


@pytest.mark.parametrize("owner", ["", " manual-1", "manual-1 ", "x" * 101, None])
def test_manual_rejects_invalid_owner_task_id(owner) -> None:
    with pytest.raises(ValueError, match="owner_task_id"):
        build_guard().run_manual("group", owner, NOW, lambda: None)


def test_manual_acquire_failure_never_calls_action() -> None:
    lock_repo = UiLockRepo(acquire_result=False)
    action_calls = []

    with pytest.raises(WechatUiBusyError, match="WeChat UI is busy"):
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: action_calls.append(True)
        )

    assert action_calls == []
    assert lock_repo.release_calls == []


def test_manual_success_acquires_and_releases_exact_owner() -> None:
    lock_repo = UiLockRepo()

    result = build_guard(ui_lock_repo=lock_repo).run_manual(
        "article", "manual-article-1", NOW, lambda: "done"
    )

    assert result == "done"
    assert lock_repo.acquire_calls == [
        ("wechat_ui", "article", "manual-article-1", NOW, 120)
    ]
    assert lock_repo.release_calls == [
        ("wechat_ui", "article", "manual-article-1")
    ]


def test_manual_action_exception_propagates_and_still_releases() -> None:
    lock_repo = UiLockRepo(release_result=False)
    expected = RuntimeError("action failed")

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group",
            "manual-1",
            NOW,
            lambda: (_ for _ in ()).throw(expected),
        )

    assert raised.value is expected
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_long_manual_action_heartbeats_ui_lease() -> None:
    lock_repo = UiLockRepo()

    def action() -> str:
        assert lock_repo.heartbeat_seen.wait(timeout=1)
        return "done"

    result = build_guard(ui_lock_repo=lock_repo).run_manual(
        "group", "manual-1", NOW, action
    )

    assert result == "done"
    assert lock_repo.heartbeat_calls
    assert lock_repo.heartbeat_calls[0] == (
        "wechat_ui",
        "group",
        "manual-1",
        NOW + timedelta(seconds=10),
    )
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_lost_manual_lease_fails_closed_after_action_and_releases() -> None:
    lock_repo = UiLockRepo(heartbeat_results=[False])

    def action() -> str:
        assert lock_repo.heartbeat_seen.wait(timeout=1)
        return "must-not-be-returned"

    with pytest.raises(WechatUiLeaseLostError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "article", "manual-1", NOW, action
        )

    assert str(raised.value) == "WeChat UI lease was lost"
    assert lock_repo.release_calls == [
        ("wechat_ui", "article", "manual-1")
    ]


def test_release_failure_never_reports_manual_success() -> None:
    lock_repo = UiLockRepo(release_result=False)
    with pytest.raises(WechatUiReleaseError, match="release"):
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "done"
        )


def test_held_lock_adapter_is_strict_and_never_touches_mysql() -> None:
    adapter = HeldUiLockAdapter("article")

    assert adapter.acquire("wechat_ui", "article", "inner-1", NOW, 120)
    assert adapter.release("wechat_ui", "article", "inner-1")

    with pytest.raises(ValueError, match="pipeline"):
        adapter.acquire("wechat_ui", "group", "inner-1", NOW, 120)
    with pytest.raises(ValueError, match="lock_name"):
        adapter.release("other", "article", "inner-1")
