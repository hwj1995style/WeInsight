from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


AUTHORIZATION_STATUSES = frozenset(
    {"valid", "expiring", "expired", "unauthorized", "unavailable"}
)


@dataclass(frozen=True, slots=True)
class WeRSSAuthorizationSnapshot:
    status: str
    account_name: str | None
    expires_at: datetime | None
    last_checked_at: datetime
    last_successful_check_at: datetime | None
    last_error_code: str | None
    authorization_version: str | None

    def __post_init__(self) -> None:
        if self.status not in AUTHORIZATION_STATUSES:
            raise ValueError("invalid authorization status")

    @property
    def needs_attention(self) -> bool:
        return self.status in {"expiring", "expired", "unauthorized"}


@dataclass(frozen=True, slots=True)
class WeRSSAuthorizationUpstreamState:
    logged_in: bool
    account_name: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthorizationNotice:
    id: int
    authorization_version: str
    notice_type: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class AuthorizationManagementSettings:
    werss_username: str
    werss_password_encrypted: bytes | None
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_encrypted: bytes | None
    smtp_security: str
    from_address: str
    recipients: tuple[str, ...]
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class PublicAuthorizationSettings:
    werss_username: str
    werss_password_configured: bool
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_configured: bool
    smtp_security: str
    from_address: str
    recipients: tuple[str, ...]
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthorizationSettingsCommand:
    werss_username: str
    werss_password: str
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_security: str
    from_address: str
    recipients: tuple[str, ...]


def authorization_version(account_name: str | None, expires_at: datetime | None) -> str | None:
    if expires_at is None:
        return None
    identity = f"{account_name or ''}\0{expires_at.isoformat(timespec='seconds')}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
