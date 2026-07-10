from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.core.config import AuthConfig
from app.security.passwords import PasswordHasher
from app.storage.admin_auth_repo import (
    AdminSessionRecord,
    AdminUserRecord,
    NewAdminSessionRecord,
)


DEFAULT_ADMIN_PASSWORD = "admin123456"


@dataclass(frozen=True)
class AuthenticatedAdmin:
    id: int
    username: str
    using_default_password: bool


@dataclass(frozen=True)
class AuthenticatedSession:
    admin: AuthenticatedAdmin
    session_token: str
    csrf_token: str
    expires_at: datetime


class InvalidCredentialsError(RuntimeError):
    pass


class LoginLockedError(RuntimeError):
    def __init__(self, locked_until: datetime) -> None:
        super().__init__(f"login locked until {locked_until.isoformat()}")
        self.locked_until = locked_until


class PasswordValidationError(ValueError):
    pass


class AdminAuthRepo(Protocol):
    def find_user_by_username(self, username: str) -> AdminUserRecord | None: ...

    def find_user_by_id(self, user_id: int) -> AdminUserRecord | None: ...

    def create_user_if_missing(self, username: str, password_hash: str) -> bool: ...

    def record_login_failure(
        self, user_id: int, locked_until: datetime | None
    ) -> None: ...

    def record_login_success(self, user_id: int, now: datetime) -> None: ...

    def update_password(
        self, user_id: int, password_hash: str, now: datetime
    ) -> None: ...

    def create_session(self, record: NewAdminSessionRecord) -> None: ...

    def find_active_session(
        self, token_hash: str, now: datetime
    ) -> AdminSessionRecord | None: ...

    def touch_session(
        self, session_id: str, idle_expires_at: datetime, now: datetime
    ) -> None: ...

    def revoke_session(self, token_hash: str, now: datetime) -> None: ...

    def revoke_user_sessions(self, user_id: int, now: datetime) -> None: ...


class AuthService:
    def __init__(
        self,
        repo: AdminAuthRepo,
        password_hasher: PasswordHasher,
        config: AuthConfig,
    ) -> None:
        self.repo = repo
        self.password_hasher = password_hasher
        self.config = config

    def ensure_bootstrap_admin(self) -> None:
        password_hash = self.password_hasher.hash(DEFAULT_ADMIN_PASSWORD)
        self.repo.create_user_if_missing(self.config.default_username, password_hash)

    def login(
        self,
        username: str,
        password: str,
        client_ip: str,
        user_agent: str,
        now: datetime,
    ) -> AuthenticatedSession:
        user = self.repo.find_user_by_username(username)
        if user is None or not user.enabled:
            raise InvalidCredentialsError("invalid username or password")
        if user.locked_until is not None and user.locked_until > now:
            raise LoginLockedError(user.locked_until)
        if not self.password_hasher.verify(user.password_hash, password):
            failed_count = user.failed_login_count + 1
            locked_until = None
            if failed_count >= self.config.login_failure_limit:
                locked_until = now + timedelta(minutes=self.config.login_lock_minutes)
            self.repo.record_login_failure(user.id, locked_until)
            raise InvalidCredentialsError("invalid username or password")

        self.repo.record_login_success(user.id, now)
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=self.config.session_absolute_minutes)
        idle_expires_at = min(
            expires_at,
            now + timedelta(minutes=self.config.session_idle_minutes),
        )
        self.repo.create_session(
            NewAdminSessionRecord(
                id=str(uuid4()),
                user_id=user.id,
                token_hash=_sha256(session_token),
                csrf_token_hash=_sha256(csrf_token),
                expires_at=expires_at,
                idle_expires_at=idle_expires_at,
                last_seen_at=now,
                client_ip=client_ip,
                user_agent_hash=_sha256(user_agent),
            )
        )
        return AuthenticatedSession(
            admin=_authenticated_admin(user),
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def authenticate(
        self, session_token: str, csrf_token: str | None, now: datetime
    ) -> AuthenticatedAdmin | None:
        session = self.repo.find_active_session(_sha256(session_token), now)
        if session is None:
            return None
        if csrf_token is not None and not _token_matches(
            session.csrf_token_hash, csrf_token
        ):
            return None
        idle_expires_at = min(
            session.expires_at,
            now + timedelta(minutes=self.config.session_idle_minutes),
        )
        self.repo.touch_session(session.id, idle_expires_at, now)
        return AuthenticatedAdmin(
            id=session.user_id,
            username=session.username,
            using_default_password=session.password_changed_at is None,
        )

    def verify_csrf(
        self, session_token: str, csrf_token: str, now: datetime
    ) -> bool:
        session = self.repo.find_active_session(_sha256(session_token), now)
        return session is not None and _token_matches(
            session.csrf_token_hash, csrf_token
        )

    def logout(self, session_token: str, now: datetime) -> None:
        self.repo.revoke_session(_sha256(session_token), now)

    def change_password(
        self,
        admin_id: int,
        current_password: str,
        new_password: str,
        now: datetime,
    ) -> None:
        if len(new_password) < 12:
            raise PasswordValidationError("new password must be at least 12 characters")
        user = self.repo.find_user_by_id(admin_id)
        if (
            user is None
            or not user.enabled
            or not self.password_hasher.verify(user.password_hash, current_password)
        ):
            raise InvalidCredentialsError("current password is invalid")
        self.repo.update_password(user.id, self.password_hasher.hash(new_password), now)
        self.repo.revoke_user_sessions(user.id, now)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_matches(expected_hash: str, supplied_token: str) -> bool:
    return hmac.compare_digest(expected_hash, _sha256(supplied_token))


def _authenticated_admin(user: AdminUserRecord) -> AuthenticatedAdmin:
    return AuthenticatedAdmin(
        id=user.id,
        username=user.username,
        using_default_password=user.password_changed_at is None,
    )
