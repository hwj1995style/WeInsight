from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.core.config import AuthConfig
from app.security.passwords import PasswordHasher
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    LoginLockedError,
    PasswordValidationError,
)
from app.storage.admin_auth_repo import (
    AdminSessionRecord,
    AdminUserRecord,
    NewAdminSessionRecord,
)


NOW = datetime(2026, 7, 10, 9, 0)


class StatefulAuthRepo:
    def __init__(self) -> None:
        self.users: dict[int, AdminUserRecord] = {}
        self.sessions: dict[str, AdminSessionRecord] = {}
        self.session_last_seen: dict[str, datetime] = {}
        self.created_username: str | None = None
        self.created_password_hash: str | None = None
        self.locked_until: datetime | None = None

    def add_user(
        self,
        password_hash: str,
        *,
        username: str = "admin",
        password_changed_at: datetime | None = None,
    ) -> AdminUserRecord:
        user = AdminUserRecord(
            id=1,
            username=username,
            password_hash=password_hash,
            enabled=True,
            password_changed_at=password_changed_at,
            failed_login_count=0,
            locked_until=None,
        )
        self.users[user.id] = user
        return user

    def find_user_by_username(self, username: str) -> AdminUserRecord | None:
        return next((user for user in self.users.values() if user.username == username), None)

    def find_user_by_id(self, user_id: int) -> AdminUserRecord | None:
        return self.users.get(user_id)

    def create_user_if_missing(self, username: str, password_hash: str) -> bool:
        self.created_username = username
        self.created_password_hash = password_hash
        if self.find_user_by_username(username) is not None:
            return False
        self.add_user(password_hash, username=username)
        return True

    def record_login_failure(self, user_id: int, locked_until: datetime | None) -> None:
        user = self.users[user_id]
        self.users[user_id] = replace(
            user,
            failed_login_count=user.failed_login_count + 1,
            locked_until=locked_until,
        )
        self.locked_until = locked_until

    def record_login_success(self, user_id: int, now: datetime) -> None:
        user = self.users[user_id]
        self.users[user_id] = replace(user, failed_login_count=0, locked_until=None)

    def update_password(self, user_id: int, password_hash: str, now: datetime) -> None:
        user = self.users[user_id]
        self.users[user_id] = replace(
            user,
            password_hash=password_hash,
            password_changed_at=now,
        )

    def create_session(self, record: NewAdminSessionRecord) -> None:
        user = self.users[record.user_id]
        self.sessions[record.token_hash] = AdminSessionRecord(
            id=record.id,
            user_id=record.user_id,
            username=user.username,
            token_hash=record.token_hash,
            csrf_token_hash=record.csrf_token_hash,
            expires_at=record.expires_at,
            idle_expires_at=record.idle_expires_at,
            revoked_at=None,
            password_changed_at=user.password_changed_at,
        )
        self.session_last_seen[record.id] = record.last_seen_at

    def find_active_session(
        self, token_hash: str, now: datetime
    ) -> AdminSessionRecord | None:
        session = self.sessions.get(token_hash)
        if session is None:
            return None
        user = self.users[session.user_id]
        if (
            session.revoked_at is not None
            or session.expires_at <= now
            or session.idle_expires_at <= now
            or not user.enabled
        ):
            return None
        return replace(session, password_changed_at=user.password_changed_at)

    def touch_session(
        self, session_id: str, idle_expires_at: datetime, now: datetime
    ) -> None:
        for token_hash, session in self.sessions.items():
            if session.id == session_id:
                self.sessions[token_hash] = replace(
                    session, idle_expires_at=idle_expires_at
                )
                self.session_last_seen[session_id] = now
                return

    def revoke_session(self, token_hash: str, now: datetime) -> None:
        session = self.sessions.get(token_hash)
        if session is not None:
            self.sessions[token_hash] = replace(session, revoked_at=now)

    def revoke_user_sessions(self, user_id: int, now: datetime) -> None:
        for token_hash, session in list(self.sessions.items()):
            if session.user_id == user_id and session.revoked_at is None:
                self.sessions[token_hash] = replace(session, revoked_at=now)


@pytest.fixture
def auth_config() -> AuthConfig:
    return AuthConfig(
        default_username="admin",
        session_cookie_name="weinsight_session",
        csrf_cookie_name="weinsight_csrf",
        session_idle_minutes=480,
        session_absolute_minutes=1440,
        login_failure_limit=5,
        login_lock_minutes=15,
    )


@pytest.fixture
def password_hasher() -> PasswordHasher:
    return PasswordHasher()


@pytest.fixture
def fake_repo(password_hasher: PasswordHasher) -> StatefulAuthRepo:
    repo = StatefulAuthRepo()
    repo.add_user(password_hasher.hash("admin123456"))
    return repo


@pytest.fixture
def auth_service(
    fake_repo: StatefulAuthRepo,
    password_hasher: PasswordHasher,
    auth_config: AuthConfig,
) -> AuthService:
    return AuthService(fake_repo, password_hasher, auth_config)


def test_bootstrap_creates_default_admin_with_argon2_hash(
    password_hasher: PasswordHasher, auth_config: AuthConfig
) -> None:
    repo = StatefulAuthRepo()
    service = AuthService(repo, password_hasher, auth_config)

    service.ensure_bootstrap_admin()

    assert repo.created_username == "admin"
    assert repo.created_password_hash != "admin123456"
    assert repo.created_password_hash is not None
    assert password_hasher.verify(repo.created_password_hash, "admin123456")


def test_first_login_marks_default_password_without_forcing_change(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    result = auth_service.login(
        username="admin",
        password="admin123456",
        client_ip="127.0.0.1",
        user_agent="pytest-agent",
        now=NOW,
    )

    assert result.admin.username == "admin"
    assert result.admin.using_default_password is True
    assert result.session_token
    assert result.csrf_token
    assert result.expires_at == NOW + timedelta(minutes=1440)
    stored = next(iter(fake_repo.sessions.values()))
    assert stored.token_hash != result.session_token
    assert stored.csrf_token_hash != result.csrf_token
    assert len(stored.token_hash) == 64
    assert len(stored.csrf_token_hash) == 64


def test_fifth_failed_login_locks_for_fifteen_minutes(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            auth_service.login("admin", "wrong", "127.0.0.1", "pytest", NOW)

    assert fake_repo.users[1].failed_login_count == 5
    assert fake_repo.locked_until == NOW + timedelta(minutes=15)


def test_login_is_rejected_while_lock_is_active(auth_service: AuthService) -> None:
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            auth_service.login("admin", "wrong", "127.0.0.1", "pytest", NOW)

    with pytest.raises(LoginLockedError) as exc_info:
        auth_service.login(
            "admin", "admin123456", "127.0.0.1", "pytest", NOW + timedelta(minutes=14)
        )

    assert exc_info.value.locked_until == NOW + timedelta(minutes=15)


def test_absolute_session_expiry_rejects_authentication(auth_service: AuthService) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    authenticated = auth_service.authenticate(
        result.session_token,
        None,
        NOW + timedelta(minutes=1440),
    )

    assert authenticated is None


def test_idle_session_expiry_rejects_authentication(auth_service: AuthService) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    authenticated = auth_service.authenticate(
        result.session_token,
        None,
        NOW + timedelta(minutes=480),
    )

    assert authenticated is None


def test_authentication_touches_idle_expiry_without_exceeding_absolute_expiry(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)
    touched_at = NOW + timedelta(minutes=60)

    authenticated = auth_service.authenticate(result.session_token, None, touched_at)

    assert authenticated is not None
    stored = next(iter(fake_repo.sessions.values()))
    assert stored.idle_expires_at == touched_at + timedelta(minutes=480)
    assert fake_repo.session_last_seen[stored.id] == touched_at


def test_authentication_checks_csrf_and_verify_csrf_uses_stored_hash(
    auth_service: AuthService,
) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    assert auth_service.verify_csrf(result.session_token, result.csrf_token, NOW)
    assert not auth_service.verify_csrf(result.session_token, "wrong-csrf", NOW)
    assert (
        auth_service.authenticate(result.session_token, "wrong-csrf", NOW) is None
    )


def test_logout_revokes_session(auth_service: AuthService) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    auth_service.logout(result.session_token, NOW + timedelta(minutes=1))

    assert auth_service.authenticate(result.session_token, None, NOW + timedelta(minutes=2)) is None


def test_change_password_requires_at_least_twelve_characters(
    auth_service: AuthService,
) -> None:
    with pytest.raises(PasswordValidationError):
        auth_service.change_password(1, "admin123456", "short-pass", NOW)


def test_change_password_updates_hash_and_revokes_user_sessions(
    auth_service: AuthService,
    fake_repo: StatefulAuthRepo,
    password_hasher: PasswordHasher,
) -> None:
    session = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    auth_service.change_password(
        1,
        "admin123456",
        "new-password-123",
        NOW + timedelta(minutes=1),
    )

    changed = fake_repo.users[1]
    assert changed.password_hash != "new-password-123"
    assert password_hasher.verify(changed.password_hash, "new-password-123")
    assert changed.password_changed_at == NOW + timedelta(minutes=1)
    assert auth_service.authenticate(session.session_token, None, NOW + timedelta(minutes=2)) is None


def test_change_password_rejects_wrong_current_password(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.change_password(1, "wrong-current", "new-password-123", NOW)


def test_corrupted_argon2_hash_is_a_safe_login_failure(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    fake_repo.users[1] = replace(fake_repo.users[1], password_hash="not-an-argon2-hash")

    with pytest.raises(InvalidCredentialsError):
        auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    assert fake_repo.users[1].failed_login_count == 1


def test_corrupted_argon2_hash_is_a_safe_change_password_failure(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    fake_repo.users[1] = replace(fake_repo.users[1], password_hash="$argon2id$broken")

    with pytest.raises(InvalidCredentialsError):
        auth_service.change_password(1, "admin123456", "new-password-123", NOW)
