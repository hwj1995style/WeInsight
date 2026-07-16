from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.domain.werss_authorization import (
    AuthorizationNotice,
    WeRSSAuthorizationSnapshot,
    WeRSSAuthorizationUpstreamState,
    authorization_version,
)
from app.integrations.werss_authorization import (
    QrStatus,
    WeRSSAuthorizationClient,
    WeRSSAuthorizationError,
)
from app.domain.werss_authorization import AuthorizationSettingsCommand


class AuthorizationRepo(Protocol):
    def get_state(self) -> WeRSSAuthorizationSnapshot | None: ...
    def upsert_state(self, snapshot: WeRSSAuthorizationSnapshot) -> None: ...
    def ensure_notice(self, snapshot: WeRSSAuthorizationSnapshot, notice_type: str, recipient_count: int) -> None: ...
    def claim_due_notice(self, now: datetime) -> AuthorizationNotice | None: ...
    def mark_notice_sent(self, notice_id: int, now: datetime) -> None: ...
    def mark_notice_retry(self, notice_id: int, now: datetime, error_code: str, attempt_count: int) -> None: ...


class AuthorizationMailer(Protocol):
    @property
    def enabled(self) -> bool: ...
    def send(self, snapshot: WeRSSAuthorizationSnapshot, notice_type: str) -> None: ...


class DynamicSettingsService(Protocol):
    def public_settings(self): ...
    def save(self, command: AuthorizationSettingsCommand, now: datetime): ...
    def management_credentials(self) -> tuple[str, str | None]: ...


@dataclass(frozen=True, slots=True)
class AuthorizationAlert:
    label: str
    status: str
    stale: bool


@dataclass(slots=True)
class _ScanSession:
    session_id: str
    admin_id: int
    image_url: str
    expires_at: datetime


class WeRSSAuthorizationService:
    def __init__(
        self,
        repo: AuthorizationRepo,
        client: WeRSSAuthorizationClient,
        *,
        warning_threshold_hours: int = 24,
        check_interval_seconds: int = 300,
        mailer: AuthorizationMailer | None = None,
        recipient_count: int = 0,
        settings_service: DynamicSettingsService | None = None,
    ) -> None:
        self.repo = repo
        self.client = client
        self.warning_threshold = timedelta(hours=warning_threshold_hours)
        self.check_interval = timedelta(seconds=check_interval_seconds)
        self.mailer = mailer
        self.recipient_count = recipient_count
        self.settings_service = settings_service
        self._cache: tuple[datetime, WeRSSAuthorizationSnapshot | None] | None = None
        self._next_monitor_at: datetime | None = None
        self._sessions: dict[str, _ScanSession] = {}
        self._lock = threading.Lock()

    @property
    def scan_configured(self) -> bool:
        if self.settings_service is not None:
            try:
                _, password = self.settings_service.management_credentials()
                return bool(password)
            except Exception:
                return False
        return self.client.scan_configured

    @property
    def email_enabled(self) -> bool:
        try:
            return bool(self.mailer and self.mailer.enabled)
        except Exception:
            return False

    def public_settings(self):
        if self.settings_service is None:
            return None
        return self.settings_service.public_settings()

    def save_settings(self, command: AuthorizationSettingsCommand, now: datetime):
        if self.settings_service is None:
            raise WeRSSAuthorizationError("werss_settings_unavailable")
        result = self.settings_service.save(command, now)
        username, password = self.settings_service.management_credentials()
        self.client.set_management_credentials(username, password)
        return result

    def test_werss_settings(self, now: datetime) -> None:
        self._apply_management_credentials()
        self.client.verify_management_credentials(now)

    def test_email_settings(self, now: datetime) -> None:
        sender = getattr(self.mailer, "send_test", None)
        if not callable(sender):
            raise WeRSSAuthorizationError("werss_email_not_configured")
        try:
            sender(now)
        except (ValueError, RuntimeError):
            raise WeRSSAuthorizationError("werss_email_not_configured") from None
        except Exception:
            raise WeRSSAuthorizationError("werss_email_test_failed") from None

    def get_state(self, now: datetime) -> WeRSSAuthorizationSnapshot | None:
        with self._lock:
            if self._cache and now - self._cache[0] < timedelta(seconds=30):
                return self._cache[1]
        state = self.repo.get_state()
        with self._lock:
            self._cache = (now, state)
        return state

    def refresh(self, now: datetime) -> WeRSSAuthorizationSnapshot:
        previous = self.repo.get_state()
        try:
            upstream = self.client.fetch_status()
            snapshot = self._snapshot_from_upstream(upstream, now)
        except WeRSSAuthorizationError as exc:
            snapshot = WeRSSAuthorizationSnapshot(
                status="unavailable",
                account_name=previous.account_name if previous else None,
                expires_at=previous.expires_at if previous else None,
                last_checked_at=now,
                last_successful_check_at=previous.last_successful_check_at if previous else None,
                last_error_code=exc.code,
                authorization_version=previous.authorization_version if previous else None,
            )
        self.repo.upsert_state(snapshot)
        with self._lock:
            self._cache = (now, snapshot)
        return snapshot

    def monitor_now(self, now: datetime) -> WeRSSAuthorizationSnapshot | None:
        with self._lock:
            if self._next_monitor_at and now < self._next_monitor_at:
                return None
            self._next_monitor_at = now + self.check_interval
        snapshot = self.refresh(now)
        if snapshot.status in {"expiring", "expired"} and snapshot.authorization_version and self.email_enabled:
            notice_type = "expired" if snapshot.status == "expired" else "expiring_24h"
            recipient_count = getattr(self.mailer, "recipient_count", self.recipient_count)
            self.repo.ensure_notice(snapshot, notice_type, recipient_count)
        self._deliver_one(now, snapshot)
        return snapshot

    def alert(self, now: datetime) -> AuthorizationAlert | None:
        snapshot = self.get_state(now)
        if snapshot is None:
            return None
        stale = snapshot.status == "unavailable"
        effective_status = snapshot.status
        if stale and snapshot.expires_at:
            effective_status = self._status_for_expiry(snapshot.expires_at, now)
        if effective_status == "expiring" and snapshot.expires_at:
            remaining = max(snapshot.expires_at - now, timedelta())
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return AuthorizationAlert(f"公众号授权将在 {hours}小时{minutes}分 后到期", "expiring", stale)
        if effective_status in {"expired", "unauthorized"}:
            return AuthorizationAlert("公众号授权已失效，待处理", effective_status, stale)
        return None

    def start_scan(self, admin_id: int, now: datetime) -> str:
        self._apply_management_credentials()
        with self._lock:
            self._remove_expired_sessions(now)
            if self._sessions:
                raise WeRSSAuthorizationError("werss_qr_busy")
        started = self.client.start_qr(now)
        session_id = uuid4().hex
        with self._lock:
            self._sessions[session_id] = _ScanSession(
                session_id, admin_id, started.image_url, now + timedelta(minutes=5)
            )
        return session_id

    def qr_image(self, session_id: str, admin_id: int, now: datetime) -> tuple[bytes, str]:
        session = self._owned_session(session_id, admin_id, now)
        return self.client.fetch_qr_image(session.image_url)

    def qr_status(self, session_id: str, admin_id: int, now: datetime) -> QrStatus:
        self._owned_session(session_id, admin_id, now)
        status = self.client.qr_status(now)
        if status.status in {"authorized", "expired"}:
            with self._lock:
                self._sessions.pop(session_id, None)
            if status.status == "authorized":
                self.refresh(now)
        return status

    def cancel_scan(self, session_id: str, admin_id: int, now: datetime) -> None:
        self._owned_session(session_id, admin_id, now)
        try:
            self.client.close_qr(now)
        finally:
            with self._lock:
                self._sessions.pop(session_id, None)

    def _snapshot_from_upstream(self, upstream: WeRSSAuthorizationUpstreamState, now: datetime) -> WeRSSAuthorizationSnapshot:
        status = "unauthorized"
        if upstream.expires_at is not None:
            status = self._status_for_expiry(upstream.expires_at, now)
        elif upstream.logged_in:
            status = "unavailable"
        return WeRSSAuthorizationSnapshot(
            status=status,
            account_name=upstream.account_name,
            expires_at=upstream.expires_at,
            last_checked_at=now,
            last_successful_check_at=now,
            last_error_code=None if status != "unavailable" else "werss_expiry_missing",
            authorization_version=authorization_version(upstream.account_name, upstream.expires_at),
        )

    def _apply_management_credentials(self) -> None:
        if self.settings_service is None:
            return
        try:
            username, password = self.settings_service.management_credentials()
        except Exception:
            raise WeRSSAuthorizationError("werss_settings_decrypt_failed") from None
        self.client.set_management_credentials(username, password)

    def _status_for_expiry(self, expires_at: datetime, now: datetime) -> str:
        remaining = expires_at - now
        if remaining <= timedelta():
            return "expired"
        if remaining <= self.warning_threshold:
            return "expiring"
        return "valid"

    def _deliver_one(self, now: datetime, snapshot: WeRSSAuthorizationSnapshot) -> None:
        if not self.email_enabled:
            return
        notice = self.repo.claim_due_notice(now)
        if notice is None:
            return
        try:
            self.mailer.send(snapshot, notice.notice_type)  # type: ignore[union-attr]
        except Exception as exc:
            self.repo.mark_notice_retry(
                notice.id,
                now,
                f"smtp_{type(exc).__name__.lower()}",
                notice.attempt_count,
            )
        else:
            self.repo.mark_notice_sent(notice.id, now)

    def _owned_session(self, session_id: str, admin_id: int, now: datetime) -> _ScanSession:
        with self._lock:
            self._remove_expired_sessions(now)
            session = self._sessions.get(session_id)
            if session is None or session.admin_id != admin_id:
                raise WeRSSAuthorizationError("werss_qr_not_found")
            return session

    def _remove_expired_sessions(self, now: datetime) -> None:
        expired = [key for key, value in self._sessions.items() if value.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)


class DisabledWeRSSAuthorizationService:
    scan_configured = False
    email_enabled = False

    def get_state(self, now: datetime):
        return None

    def alert(self, now: datetime):
        return None

    def refresh(self, now: datetime):
        raise WeRSSAuthorizationError("werss_authorization_disabled")

    def monitor_now(self, now: datetime):
        return None

    def public_settings(self):
        return None
