from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.rpa.desktop_probe import (
    WechatDesktopProbe,
    WechatHealth,
    WechatHealthStatus,
)
from app.storage.collection_event_repo import NewCollectionEvent, sanitize_output
from app.storage.wechat_health_repo import (
    NewWechatHealthCheck,
    WechatHealthRecord,
)


@dataclass(frozen=True, slots=True)
class WechatHealthSnapshot:
    status: WechatHealthStatus
    message: str
    checked_at: datetime
    detected_version: str | None
    consecutive_failure_count: int
    deep_check_deferred: bool


class BooleanHealthProbe(Protocol):
    def check(self) -> bool: ...


class UiLockOwnerReader(Protocol):
    def current_owner(
        self, lock_name: str, now: datetime | None = None
    ) -> str | None: ...


class WechatHealthRepo(Protocol):
    def insert_check(self, check: NewWechatHealthCheck) -> WechatHealthRecord: ...

    def latest_check(self, hostname: str) -> WechatHealthRecord | None: ...

    def consecutive_failure_count(self, hostname: str) -> int: ...


class CollectionEventWriter(Protocol):
    def append_event(self, event: NewCollectionEvent) -> int: ...


class WechatHealthMonitor:
    def __init__(
        self,
        *,
        desktop_probe: WechatDesktopProbe,
        window_probe: BooleanHealthProbe,
        login_probe: BooleanHealthProbe,
        rpa_probe: BooleanHealthProbe,
        ui_lock_repo: UiLockOwnerReader,
        health_repo: WechatHealthRepo,
        event_repo: CollectionEventWriter,
        hostname: str,
        worker_id: str,
        check_login_interval_seconds: int,
    ) -> None:
        _required_text(hostname, "hostname", 255)
        _required_text(worker_id, "worker_id", 100)
        if (
            isinstance(check_login_interval_seconds, bool)
            or not isinstance(check_login_interval_seconds, int)
            or check_login_interval_seconds < 1
        ):
            raise ValueError("check_login_interval_seconds must be a positive integer")
        self.desktop_probe = desktop_probe
        self.window_probe = window_probe
        self.login_probe = login_probe
        self.rpa_probe = rpa_probe
        self.ui_lock_repo = ui_lock_repo
        self.health_repo = health_repo
        self.event_repo = event_repo
        self.hostname = hostname
        self.worker_id = worker_id
        self.check_login_interval_seconds = check_login_interval_seconds

    def run_check(self, now: datetime) -> WechatHealthSnapshot:
        _require_shanghai_datetime(now, "now")
        desktop_health = self._check_desktop(now)
        if isinstance(desktop_health, WechatHealthSnapshot):
            return desktop_health

        detected_version = _safe_version(desktop_health.version)
        if desktop_health.status is WechatHealthStatus.NOT_RUNNING:
            return self._persist(
                WechatHealthStatus.NOT_RUNNING,
                desktop_health.message,
                now,
                detected_version,
            )
        if desktop_health.status is WechatHealthStatus.VERSION_MISMATCH:
            return self._persist(
                WechatHealthStatus.VERSION_MISMATCH,
                desktop_health.message,
                now,
                detected_version,
            )
        if desktop_health.status is not WechatHealthStatus.OK:
            return self._persist(
                WechatHealthStatus.RPA_UNAVAILABLE,
                "Desktop probe returned an unsupported shallow health state.",
                now,
                detected_version,
            )

        try:
            ui_owner = self.ui_lock_repo.current_owner("wechat_ui", now)
        except Exception:
            return self._persist(
                WechatHealthStatus.RPA_UNAVAILABLE,
                "WeChat UI lock state is unavailable.",
                now,
                detected_version,
            )
        if ui_owner is not None:
            return self._defer_deep_check(now)

        available, failed_by_exception = _run_boolean_probe(self.window_probe)
        if not available:
            return self._persist(
                WechatHealthStatus.WINDOW_UNAVAILABLE,
                (
                    "WeChat window probe failed safely."
                    if failed_by_exception
                    else "WeChat main window is unavailable."
                ),
                now,
                detected_version,
            )

        available, failed_by_exception = _run_boolean_probe(self.login_probe)
        if not available:
            return self._persist(
                WechatHealthStatus.NOT_LOGGED_IN,
                (
                    "WeChat login probe failed safely."
                    if failed_by_exception
                    else "WeChat is not logged in."
                ),
                now,
                detected_version,
            )

        available, failed_by_exception = _run_boolean_probe(self.rpa_probe)
        if not available:
            return self._persist(
                WechatHealthStatus.RPA_UNAVAILABLE,
                (
                    "WeChat RPA probe failed safely."
                    if failed_by_exception
                    else "WeChat RPA adapter is unavailable."
                ),
                now,
                detected_version,
            )

        return self._persist(
            WechatHealthStatus.OK,
            "WeChat client is healthy.",
            now,
            detected_version,
        )

    @property
    def latest_status(self) -> WechatHealthStatus | None:
        try:
            latest = self.health_repo.latest_check(self.hostname)
        except Exception:
            return None
        return None if latest is None else latest.status

    def can_collect(self, now: datetime) -> bool:
        _require_shanghai_datetime(now, "now")
        try:
            latest = self.health_repo.latest_check(self.hostname)
        except Exception:
            return False
        if latest is None or latest.status is not WechatHealthStatus.OK:
            return False
        age = now - latest.checked_at
        return timedelta(0) <= age <= timedelta(
            seconds=2 * self.check_login_interval_seconds
        )

    def _check_desktop(
        self, now: datetime
    ) -> WechatHealth | WechatHealthSnapshot:
        try:
            result = self.desktop_probe.check()
        except Exception:
            return self._persist(
                WechatHealthStatus.NOT_RUNNING,
                "WeChat desktop process probe failed safely.",
                now,
                None,
            )
        if not isinstance(result, WechatHealth):
            return self._persist(
                WechatHealthStatus.NOT_RUNNING,
                "WeChat desktop process probe returned an invalid result.",
                now,
                None,
            )
        return result

    def _persist(
        self,
        status: WechatHealthStatus,
        message: str,
        now: datetime,
        detected_version: str | None,
    ) -> WechatHealthSnapshot:
        record = self.health_repo.insert_check(
            NewWechatHealthCheck(
                worker_id=self.worker_id,
                hostname=self.hostname,
                status=status,
                detected_version=detected_version,
                message=sanitize_output(message, maximum=1000),
                checked_at=now,
            )
        )
        return _snapshot_from_record(record, deep_check_deferred=False)

    def _defer_deep_check(self, now: datetime) -> WechatHealthSnapshot:
        latest = self.health_repo.latest_check(self.hostname)
        self.event_repo.append_event(
            NewCollectionEvent(
                job_id=None,
                run_id=None,
                target_run_id=None,
                worker_id=self.worker_id,
                level="info",
                event_type="wechat_health_deep_check_deferred",
                stage="health_check",
                message="WeChat UI is busy; deep health check was deferred.",
                metrics_json=json.dumps(
                    {"busy": True, "lock_name": "wechat_ui"},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                actor_type="worker",
                actor_name=self.worker_id,
            )
        )
        if latest is None:
            return WechatHealthSnapshot(
                status=WechatHealthStatus.RPA_UNAVAILABLE,
                message="Deep health check deferred with no complete health history.",
                checked_at=now,
                detected_version=None,
                consecutive_failure_count=0,
                deep_check_deferred=True,
            )
        return _snapshot_from_record(latest, deep_check_deferred=True)


def _run_boolean_probe(probe: BooleanHealthProbe) -> tuple[bool, bool]:
    try:
        result = probe.check()
    except Exception:
        return False, True
    return result is True, False


def _snapshot_from_record(
    record: WechatHealthRecord, *, deep_check_deferred: bool
) -> WechatHealthSnapshot:
    return WechatHealthSnapshot(
        status=record.status,
        message=sanitize_output(record.message, maximum=1000),
        checked_at=record.checked_at,
        detected_version=_safe_version(record.detected_version),
        consecutive_failure_count=record.consecutive_failure_count,
        deep_check_deferred=deep_check_deferred,
    )


def _safe_version(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    safe = sanitize_output(value, maximum=100).strip()
    return safe or None


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _require_shanghai_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if (
        not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != APPLICATION_TIMEZONE
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field} must use {APPLICATION_TIMEZONE} ZoneInfo"
        )
    return value
