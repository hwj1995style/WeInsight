from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2 import extract_parameters

from app.core.config import AuthConfig
from app.security.passwords import PasswordHasher
from app.services.auth_service import (
    AuthService,
    DUMMY_PASSWORD_HASH,
    InvalidCredentialsError,
    LoginLockedError,
    PasswordValidationError,
)
from app.storage.admin_auth_repo import (
    AdminSessionRecord,
    AdminUserRecord,
    MysqlAdminAuthRepo,
    NewAdminSessionRecord,
)


NOW = datetime(2026, 7, 10, 9, 0)


class BootstrapResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class OwnerTableConnection:
    def __init__(self, usernames: list[str]) -> None:
        self.usernames = usernames

    def execute(self, statement, params=None):
        sql = str(statement)
        username = str(params["username"])
        if "WHERE NOT EXISTS" in sql and self.usernames:
            return BootstrapResult(0)
        if username in self.usernames:
            return BootstrapResult(0)
        self.usernames.append(username)
        return BootstrapResult(1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OwnerTableEngine:
    def __init__(self) -> None:
        self.connection = OwnerTableConnection(["owner"])

    def begin(self):
        return self.connection


class StatefulAuthRepo:
    def __init__(self) -> None:
        self.users: dict[int, AdminUserRecord] = {}
        self.sessions: dict[str, AdminSessionRecord] = {}
        self.new_sessions: list[NewAdminSessionRecord] = []
        self.session_last_seen: dict[str, datetime] = {}
        self.created_username: str | None = None
        self.created_password_hash: str | None = None
        self.locked_until: datetime | None = None
        self.atomic_password_updates = 0
        self.state_lock = threading.Lock()
        self.stale_read_barrier: threading.Barrier | None = None

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
        with self.state_lock:
            user = next(
                (user for user in self.users.values() if user.username == username),
                None,
            )
        if user is not None and self.stale_read_barrier is not None:
            self.stale_read_barrier.wait()
        return user

    def find_user_by_id(self, user_id: int) -> AdminUserRecord | None:
        return self.users.get(user_id)

    def create_user_if_missing(self, username: str, password_hash: str) -> bool:
        self.created_username = username
        self.created_password_hash = password_hash
        if self.users:
            return False
        self.add_user(password_hash, username=username)
        return True

    def record_login_failure(
        self,
        user_id: int,
        now: datetime,
        failure_limit: int,
        lock_minutes: int,
    ) -> datetime | None:
        with self.state_lock:
            user = self.users[user_id]
            failed_login_count = user.failed_login_count + 1
            if user.locked_until is not None and user.locked_until > now:
                locked_until = user.locked_until
            elif failed_login_count >= failure_limit:
                locked_until = now + timedelta(minutes=lock_minutes)
            else:
                locked_until = None
            self.users[user_id] = replace(
                user,
                failed_login_count=failed_login_count,
                locked_until=locked_until,
            )
            self.locked_until = locked_until
            return locked_until

    def record_login_success(self, user_id: int, now: datetime) -> None:
        user = self.users[user_id]
        self.users[user_id] = replace(user, failed_login_count=0, locked_until=None)

    def update_password_and_revoke_sessions(
        self, user_id: int, password_hash: str, now: datetime
    ) -> None:
        self.atomic_password_updates += 1
        user = self.users[user_id]
        self.users[user_id] = replace(
            user,
            password_hash=password_hash,
            password_changed_at=now,
        )
        for token_hash, session in list(self.sessions.items()):
            if session.user_id == user_id and session.revoked_at is None:
                self.sessions[token_hash] = replace(session, revoked_at=now)

    def create_session(self, record: NewAdminSessionRecord) -> None:
        user = self.users[record.user_id]
        self.new_sessions.append(record)
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

class FailIfVerifiedHasher:
    def hash(self, password: str) -> str:
        raise AssertionError("hash must not be called")

    def verify(self, password_hash: str, password: str) -> bool:
        raise AssertionError("verify must not be called")


class RecordingRejectingHasher:
    def __init__(self) -> None:
        self.verify_calls: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
        raise AssertionError("hash must not be called")

    def verify(self, password_hash: str, password: str) -> bool:
        self.verify_calls.append((password_hash, password))
        return False


@pytest.fixture
def auth_config() -> AuthConfig:
    return AuthConfig(
        default_username="admin",
        session_cookie_name="weinsight_session",
        csrf_cookie_name="weinsight_csrf",
        login_csrf_cookie_name="weinsight_dev_login_csrf",
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


def test_bootstrap_does_not_create_admin_when_different_owner_exists(
    password_hasher: PasswordHasher, auth_config: AuthConfig
) -> None:
    engine = OwnerTableEngine()
    repo = MysqlAdminAuthRepo(engine)
    service = AuthService(repo, password_hasher, auth_config)

    service.ensure_bootstrap_admin()

    assert engine.connection.usernames == ["owner"]


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


def test_login_persists_only_sha256_user_agent_hash(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    user_agent = "Mozilla/5.0 pytest security review"

    auth_service.login(
        "admin",
        "admin123456",
        "127.0.0.1",
        user_agent,
        NOW,
    )

    stored = fake_repo.new_sessions[0]
    assert stored.user_agent_hash == hashlib.sha256(
        user_agent.encode("utf-8")
    ).hexdigest()
    assert stored.user_agent_hash != user_agent


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


def test_concurrent_failures_use_current_count_and_lock_the_fifth_attempt(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    fake_repo.users[1] = replace(fake_repo.users[1], failed_login_count=3)
    fake_repo.stale_read_barrier = threading.Barrier(2)

    def fail_login() -> type[BaseException]:
        try:
            auth_service.login("admin", "wrong", "127.0.0.1", "pytest", NOW)
        except BaseException as exc:
            return type(exc)
        raise AssertionError("failed login unexpectedly succeeded")

    with ThreadPoolExecutor(max_workers=2) as pool:
        errors = list(pool.map(lambda _: fail_login(), range(2)))

    assert errors == [InvalidCredentialsError, InvalidCredentialsError]
    assert fake_repo.users[1].failed_login_count == 5
    assert fake_repo.users[1].locked_until == NOW + timedelta(minutes=15)


def test_locked_login_does_not_verify_password(
    fake_repo: StatefulAuthRepo, auth_config: AuthConfig
) -> None:
    fake_repo.users[1] = replace(
        fake_repo.users[1], locked_until=NOW + timedelta(minutes=15)
    )
    service = AuthService(fake_repo, FailIfVerifiedHasher(), auth_config)

    with pytest.raises(LoginLockedError):
        service.login("admin", "anything", "127.0.0.1", "pytest", NOW)


def test_successful_login_resets_failures_and_expired_lock(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    fake_repo.users[1] = replace(
        fake_repo.users[1],
        failed_login_count=4,
        locked_until=NOW - timedelta(seconds=1),
    )

    auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)

    assert fake_repo.users[1].failed_login_count == 0
    assert fake_repo.users[1].locked_until is None


def test_disabled_user_runs_dummy_verification_before_rejection(
    fake_repo: StatefulAuthRepo, auth_config: AuthConfig
) -> None:
    fake_repo.users[1] = replace(fake_repo.users[1], enabled=False)
    hasher = RecordingRejectingHasher()
    service = AuthService(fake_repo, hasher, auth_config)

    with pytest.raises(InvalidCredentialsError):
        service.login("admin", "anything", "127.0.0.1", "pytest", NOW)

    assert len(hasher.verify_calls) == 1
    assert hasher.verify_calls[0][0] != fake_repo.users[1].password_hash


def test_missing_user_runs_dummy_verification_before_rejection(
    fake_repo: StatefulAuthRepo, auth_config: AuthConfig
) -> None:
    hasher = RecordingRejectingHasher()
    service = AuthService(fake_repo, hasher, auth_config)

    with pytest.raises(InvalidCredentialsError):
        service.login("missing", "anything", "127.0.0.1", "pytest", NOW)

    assert len(hasher.verify_calls) == 1


def test_dummy_password_hash_is_valid_and_matches_production_cost() -> None:
    hasher = Argon2PasswordHasher()
    parameters = extract_parameters(DUMMY_PASSWORD_HASH)

    assert hasher.verify(
        DUMMY_PASSWORD_HASH,
        "weinsight-dummy-password-check",
    )
    assert parameters.memory_cost == hasher.memory_cost
    assert parameters.time_cost == hasher.time_cost
    assert parameters.parallelism == hasher.parallelism
    assert parameters.hash_len == hasher.hash_len
    assert parameters.salt_len == hasher.salt_len


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


def test_touch_caps_idle_expiry_at_absolute_session_expiry(
    auth_service: AuthService, fake_repo: StatefulAuthRepo
) -> None:
    result = auth_service.login("admin", "admin123456", "127.0.0.1", "pytest", NOW)
    token_hash, stored = next(iter(fake_repo.sessions.items()))
    fake_repo.sessions[token_hash] = replace(
        stored,
        idle_expires_at=stored.expires_at,
    )
    touched_at = stored.expires_at - timedelta(minutes=30)

    authenticated = auth_service.authenticate(result.session_token, None, touched_at)

    assert authenticated is not None
    assert fake_repo.sessions[token_hash].idle_expires_at == stored.expires_at


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
    assert fake_repo.atomic_password_updates == 1
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
