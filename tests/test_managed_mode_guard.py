from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import app.services.managed_mode_guard as guard_module

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
        release_error: Exception | None = None,
    ) -> None:
        self.acquire_result = acquire_result
        self.heartbeat_results = list(heartbeat_results or [True])
        self.release_result = release_result
        self.release_error = release_error
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
            result = self.heartbeat_results.pop(0)
        else:
            result = self.heartbeat_results[0]
        if isinstance(result, BaseException):
            raise result
        return result

    def release(
        self, lock_name: str, owner_pipeline: str, owner_task_id: str
    ) -> bool:
        self.release_calls.append((lock_name, owner_pipeline, owner_task_id))
        if self.release_error is not None:
            raise self.release_error
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


def test_thread_constructor_failure_still_releases_lock(monkeypatch) -> None:
    lock_repo = UiLockRepo()
    expected = RuntimeError("thread constructor failed")

    def fail_thread(**kwargs):
        raise expected

    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            Lock=threading.Lock,
            Thread=fail_thread,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "unused"
        )

    assert raised.value is expected
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]
    assert _active_lease_threads() == []


def test_event_constructor_failure_still_releases_lock(monkeypatch) -> None:
    lock_repo = UiLockRepo()
    expected = RuntimeError("event constructor failed")

    def fail_event():
        raise expected

    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=fail_event,
            Lock=threading.Lock,
            Thread=threading.Thread,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "article", "manual-1", NOW, lambda: "unused"
        )

    assert raised.value is expected
    assert lock_repo.release_calls == [
        ("wechat_ui", "article", "manual-1")
    ]
    assert _active_lease_threads() == []


def test_thread_start_failure_still_releases_without_join(monkeypatch) -> None:
    lock_repo = UiLockRepo()
    expected = RuntimeError("thread start failed")

    class StartFailureThread:
        join_calls = 0

        def __init__(self, **kwargs) -> None:
            pass

        def start(self) -> None:
            raise expected

        def join(self) -> None:
            self.join_calls += 1

        def is_alive(self) -> bool:
            raise ValueError("thread state unavailable")

    thread = StartFailureThread()
    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            Lock=threading.Lock,
            Thread=lambda **kwargs: thread,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "unused"
        )

    assert raised.value is expected
    assert thread.join_calls == 0
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_thread_join_failure_rechecks_liveness_and_still_releases(monkeypatch) -> None:
    lock_repo = UiLockRepo()
    expected = RuntimeError("thread join failed")

    class JoinFailureThread:
        def __init__(self, **kwargs) -> None:
            self.join_calls = 0
            self.join_timeouts = []
            self.active = False

        def start(self) -> None:
            self.active = True

        def join(self, timeout=None) -> None:
            self.join_calls += 1
            self.join_timeouts.append(timeout)
            self.active = False
            if self.join_calls == 1:
                raise expected

        def is_alive(self) -> bool:
            return self.active

    thread = JoinFailureThread()
    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            Lock=threading.Lock,
            Thread=lambda **kwargs: thread,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "done"
        )

    assert raised.value is expected
    assert thread.join_calls == 1
    assert thread.join_timeouts[0] is not None
    assert thread.is_alive() is False
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_stop_wakeup_failure_exits_within_interval_without_extra_heartbeat(
    monkeypatch,
) -> None:
    lock_repo = UiLockRepo(heartbeat_results=[False])
    expected = RuntimeError("wake event set failed")

    class FailingWakeEvent:
        def __init__(self) -> None:
            self.inner = threading.Event()

        def wait(self, timeout=None):
            return self.inner.wait(timeout)

        def set(self) -> None:
            raise expected

    events = iter([FailingWakeEvent(), threading.Event()])
    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=lambda: next(events),
            Lock=threading.Lock,
            Thread=threading.Thread,
        ),
    )

    started = datetime.now()
    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "done"
        )
    elapsed = datetime.now() - started

    assert raised.value is expected
    assert elapsed < timedelta(seconds=0.5)
    assert lock_repo.heartbeat_calls == []
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]
    assert _active_lease_threads() == []


def test_continuous_join_errors_are_bounded_and_never_skip_release(
    monkeypatch,
) -> None:
    lock_repo = UiLockRepo()
    expected = RuntimeError("join failed continuously")

    class BoundedFailureThread:
        def __init__(self, **kwargs) -> None:
            self.join_timeouts = []
            self.alive_checks = 0
            self.active = False

        def start(self) -> None:
            self.active = True

        def join(self, timeout=None) -> None:
            self.join_timeouts.append(timeout)
            raise expected

        def is_alive(self) -> bool:
            self.alive_checks += 1
            if self.alive_checks >= 3:
                self.active = False
            return self.active

    thread = BoundedFailureThread()
    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            Lock=threading.Lock,
            Thread=lambda **kwargs: thread,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "article", "manual-1", NOW, lambda: "done"
        )

    assert raised.value is expected
    assert len(thread.join_timeouts) == 3
    assert all(timeout is not None for timeout in thread.join_timeouts)
    assert thread.is_alive() is False
    assert lock_repo.release_calls == [
        ("wechat_ui", "article", "manual-1")
    ]


def test_still_live_renewer_marks_lease_lost_and_releases_without_success(
    monkeypatch,
) -> None:
    lock_repo = UiLockRepo()

    class NeverStopsThread:
        def __init__(self, **kwargs) -> None:
            self.join_timeouts = []

        def start(self) -> None:
            return None

        def join(self, timeout=None) -> None:
            self.join_timeouts.append(timeout)

        def is_alive(self) -> bool:
            return True

    thread = NeverStopsThread()
    monkeypatch.setattr(
        guard_module,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            Lock=threading.Lock,
            Thread=lambda **kwargs: thread,
        ),
    )

    started = datetime.now()
    with pytest.raises(WechatUiLeaseLostError, match="thread did not stop"):
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, lambda: "must-not-return"
        )
    elapsed = datetime.now() - started

    assert elapsed < timedelta(seconds=0.5)
    assert len(thread.join_timeouts) == 3
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_inflight_heartbeat_finishes_then_thread_exits_before_release() -> None:
    heartbeat_started = threading.Event()
    allow_heartbeat_to_finish = threading.Event()

    class InflightHeartbeatRepo(UiLockRepo):
        def heartbeat(self, *args, **kwargs) -> bool:
            heartbeat_started.set()
            assert allow_heartbeat_to_finish.wait(timeout=1)
            return super().heartbeat(*args, **kwargs)

    lock_repo = InflightHeartbeatRepo()

    def action() -> str:
        assert heartbeat_started.wait(timeout=1)
        threading.Timer(0.02, allow_heartbeat_to_finish.set).start()
        return "done"

    result = build_guard(ui_lock_repo=lock_repo).run_manual(
        "group", "manual-1", NOW, action
    )

    assert result == "done"
    assert _active_lease_threads() == []
    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]


def test_heartbeat_exception_loses_lease_releases_and_leaves_no_thread() -> None:
    lock_repo = UiLockRepo(
        heartbeat_results=[RuntimeError("database heartbeat failed")]
    )

    def action() -> str:
        assert lock_repo.heartbeat_seen.wait(timeout=1)
        return "must-not-be-returned"

    with pytest.raises(WechatUiLeaseLostError):
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "group", "manual-1", NOW, action
        )

    assert lock_repo.release_calls == [("wechat_ui", "group", "manual-1")]
    assert _active_lease_threads() == []


def test_action_exception_wins_over_release_exception_and_thread_stops() -> None:
    expected = RuntimeError("action failed")
    lock_repo = UiLockRepo(
        release_error=RuntimeError("release failed")
    )

    with pytest.raises(RuntimeError) as raised:
        build_guard(ui_lock_repo=lock_repo).run_manual(
            "article",
            "manual-1",
            NOW,
            lambda: (_ for _ in ()).throw(expected),
        )

    assert raised.value is expected
    assert lock_repo.release_calls == [
        ("wechat_ui", "article", "manual-1")
    ]
    assert _active_lease_threads() == []


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), float("-inf")])
def test_guard_rejects_nonfinite_heartbeat_interval(interval) -> None:
    with pytest.raises(ValueError, match="positive number"):
        ManagedModeGuard(
            heartbeat_repo=HeartbeatRepo(),
            ui_lock_repo=UiLockRepo(),
            hostname="HOST-A",
            collector_heartbeat_ttl_seconds=30,
            ui_lease_seconds=120,
            ui_heartbeat_interval_seconds=interval,
        )


def test_guard_accepts_integer_heartbeat_interval_from_config() -> None:
    guard = ManagedModeGuard(
        heartbeat_repo=HeartbeatRepo(),
        ui_lock_repo=UiLockRepo(),
        hostname="HOST-A",
        collector_heartbeat_ttl_seconds=30,
        ui_lease_seconds=120,
        ui_heartbeat_interval_seconds=10,
    )
    assert guard.ui_heartbeat_interval_seconds == 10


def test_held_lock_adapter_is_strict_and_never_touches_mysql() -> None:
    adapter = HeldUiLockAdapter("article")

    assert adapter.acquire("wechat_ui", "article", "inner-1", NOW, 120)
    assert adapter.release("wechat_ui", "article", "inner-1")

    with pytest.raises(ValueError, match="pipeline"):
        adapter.acquire("wechat_ui", "group", "inner-1", NOW, 120)
    with pytest.raises(ValueError, match="lock_name"):
        adapter.release("other", "article", "inner-1")


def _active_lease_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("wechat-ui-lease-")
        and thread.is_alive()
    ]
