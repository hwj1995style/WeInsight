from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    ensure_schedule_datetime,
)


T = TypeVar("T")
_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_PIPELINES = frozenset({"group", "article"})


class ManagedModeActiveError(RuntimeError):
    pass


class WechatUiBusyError(RuntimeError):
    pass


class WechatUiLeaseLostError(RuntimeError):
    pass


class WechatUiReleaseError(RuntimeError):
    pass


class HeartbeatRepo(Protocol):
    def has_live_collector(
        self,
        hostname: str,
        now: datetime,
        ttl_seconds: int,
        exclude_worker_id: str | None = None,
    ) -> bool: ...


class UiLockRepo(Protocol):
    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool: ...

    def heartbeat(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
    ) -> bool: ...

    def release(
        self, lock_name: str, owner_pipeline: str, owner_task_id: str
    ) -> bool: ...


class ManagedModeGuard:
    def __init__(
        self,
        *,
        heartbeat_repo: HeartbeatRepo,
        ui_lock_repo: UiLockRepo,
        hostname: str,
        collector_heartbeat_ttl_seconds: int,
        ui_lease_seconds: int,
        ui_heartbeat_interval_seconds: int | float,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        _required_text(hostname, "hostname", 255)
        _positive_integer(
            collector_heartbeat_ttl_seconds,
            "collector_heartbeat_ttl_seconds",
        )
        _positive_integer(ui_lease_seconds, "ui_lease_seconds")
        _positive_number(
            ui_heartbeat_interval_seconds,
            "ui_heartbeat_interval_seconds",
        )
        if ui_heartbeat_interval_seconds >= ui_lease_seconds:
            raise ValueError(
                "ui_heartbeat_interval_seconds must be less than ui_lease_seconds"
            )
        if now_provider is not None and not callable(now_provider):
            raise TypeError("now_provider must be callable or None")
        self.heartbeat_repo = heartbeat_repo
        self.ui_lock_repo = ui_lock_repo
        self.hostname = hostname
        self.collector_heartbeat_ttl_seconds = (
            collector_heartbeat_ttl_seconds
        )
        self.ui_lease_seconds = ui_lease_seconds
        self.ui_heartbeat_interval_seconds = ui_heartbeat_interval_seconds
        self.now_provider = now_provider or _shanghai_now

    def ensure_scheduler_allowed(self, now: datetime) -> None:
        _require_now(now)
        live = self.heartbeat_repo.has_live_collector(
            self.hostname,
            now,
            self.collector_heartbeat_ttl_seconds,
        )
        if not isinstance(live, bool):
            raise TypeError("has_live_collector must return bool")
        if live:
            raise ManagedModeActiveError("managed collector is active")

    def run_manual(
        self,
        pipeline: str,
        owner_task_id: str,
        now: datetime,
        action: Callable[[], T],
    ) -> T:
        _pipeline(pipeline)
        _required_text(owner_task_id, "owner_task_id", 100)
        _require_now(now)
        if not callable(action):
            raise TypeError("action must be callable")
        acquired = self.ui_lock_repo.acquire(
            "wechat_ui",
            pipeline,
            owner_task_id,
            now,
            self.ui_lease_seconds,
        )
        if acquired is not True:
            raise WechatUiBusyError("WeChat UI is busy")

        stop = threading.Event()
        lease_lost = threading.Event()

        def renew_lease() -> None:
            while not stop.wait(self.ui_heartbeat_interval_seconds):
                try:
                    heartbeat_now = self.now_provider()
                    _require_now(heartbeat_now)
                    renewed = self.ui_lock_repo.heartbeat(
                        "wechat_ui",
                        pipeline,
                        owner_task_id,
                        heartbeat_now,
                    )
                except Exception:
                    lease_lost.set()
                    return
                if renewed is not True:
                    lease_lost.set()
                    return

        renewer = threading.Thread(
            target=renew_lease,
            name=f"wechat-ui-lease-{pipeline}",
            daemon=True,
        )
        try:
            renewer.start()
        except BaseException:
            self._release(pipeline, owner_task_id)
            raise

        try:
            result = action()
        except BaseException:
            stop.set()
            renewer.join()
            self._release(pipeline, owner_task_id)
            raise

        stop.set()
        renewer.join()
        released = self._release(pipeline, owner_task_id)
        if lease_lost.is_set():
            raise WechatUiLeaseLostError("WeChat UI lease was lost")
        if not released:
            raise WechatUiReleaseError("failed to release WeChat UI lock")
        return result

    def _release(self, pipeline: str, owner_task_id: str) -> bool:
        try:
            return (
                self.ui_lock_repo.release(
                    "wechat_ui", pipeline, owner_task_id
                )
                is True
            )
        except Exception:
            return False


class HeldUiLockAdapter:
    """Strict no-op adapter for a runner executing under an outer UI lock."""

    def __init__(self, pipeline: str) -> None:
        _pipeline(pipeline)
        self.pipeline = pipeline

    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        self._validate_owner(lock_name, owner_pipeline, owner_task_id)
        _require_now(now)
        _positive_integer(lease_seconds, "lease_seconds")
        return True

    def release(
        self, lock_name: str, owner_pipeline: str, owner_task_id: str
    ) -> bool:
        self._validate_owner(lock_name, owner_pipeline, owner_task_id)
        return True

    def _validate_owner(
        self, lock_name: str, owner_pipeline: str, owner_task_id: str
    ) -> None:
        if lock_name != "wechat_ui":
            raise ValueError("lock_name must be wechat_ui")
        if owner_pipeline != self.pipeline:
            raise ValueError("owner_pipeline does not match held pipeline")
        _required_text(owner_task_id, "owner_task_id", 100)


def _pipeline(value: object) -> str:
    if value not in _PIPELINES:
        raise ValueError("pipeline must be group or article")
    return str(value)


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _positive_number(value: object, field: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise ValueError(f"{field} must be a positive number")


def _require_now(value: object) -> None:
    ensure_schedule_datetime(value, field_name="now")


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)
