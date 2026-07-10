from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from app.storage.admin_auth_repo import MysqlAdminAuthRepo, NewAdminSessionRecord


NOW = datetime(2026, 7, 10, 9, 0)


class FakeResult:
    def __init__(self, row=None, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict[str, object]]] = []
        self.admin_user_row = {
            "id": 7,
            "username": "admin",
            "password_hash": "$argon2id$stored-hash",
            "enabled": 1,
            "password_changed_at": None,
            "failed_login_count": 2,
            "locked_until": None,
        }

    def execute(self, statement, params=None):
        sql = str(statement)
        bound = dict(params or {})
        self.executions.append((sql, bound))
        if "FROM weinsight_admin_user" in sql:
            return FakeResult(dict(self.admin_user_row))
        if "FROM weinsight_admin_session" in sql:
            return FakeResult(
                {
                    "id": "session-id",
                    "user_id": 7,
                    "username": "admin",
                    "token_hash": "a" * 64,
                    "csrf_token_hash": "b" * 64,
                    "expires_at": NOW + timedelta(days=1),
                    "idle_expires_at": NOW + timedelta(hours=8),
                    "revoked_at": None,
                    "password_changed_at": None,
                }
            )
        return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


class BootstrapStateConnection:
    def __init__(self, engine: BootstrapStateEngine) -> None:
        self.engine = engine

    def execute(self, statement, params=None):
        sql = str(statement)
        bound = dict(params or {})
        with self.engine.lock:
            if "WHERE NOT EXISTS" in sql and self.engine.usernames:
                return FakeResult(rowcount=0)
            username = str(bound["username"])
            if username in self.engine.usernames:
                return FakeResult(rowcount=0)
            self.engine.usernames.append(username)
            return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class BootstrapStateEngine:
    def __init__(self, usernames: list[str]) -> None:
        self.usernames = usernames
        self.lock = threading.Lock()

    def begin(self):
        return BootstrapStateConnection(self)


class PasswordTransactionConnection:
    def __init__(self, engine: PasswordTransactionEngine) -> None:
        self.engine = engine
        self.password_hash = engine.password_hash
        self.password_changed_at = engine.password_changed_at
        self.sessions_revoked_at = engine.sessions_revoked_at
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        bound = dict(params or {})
        self.executions.append((sql, bound))
        if "UPDATE weinsight_admin_user" in sql:
            self.password_hash = str(bound["password_hash"])
            self.password_changed_at = bound["now"]
            return FakeResult(rowcount=1)
        if "UPDATE weinsight_admin_session" in sql:
            if self.engine.fail_session_update:
                raise RuntimeError("session update failed")
            self.sessions_revoked_at = bound["now"]
            return FakeResult(rowcount=2)
        raise AssertionError(f"unexpected SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.engine.password_hash = self.password_hash
            self.engine.password_changed_at = self.password_changed_at
            self.engine.sessions_revoked_at = self.sessions_revoked_at
        return False


class PasswordTransactionEngine:
    def __init__(self, *, fail_session_update: bool) -> None:
        self.fail_session_update = fail_session_update
        self.password_hash = "$argon2id$original-hash"
        self.password_changed_at: datetime | None = None
        self.sessions_revoked_at: datetime | None = None
        self.begin_count = 0
        self.connections: list[PasswordTransactionConnection] = []

    def begin(self):
        self.begin_count += 1
        connection = PasswordTransactionConnection(self)
        self.connections.append(connection)
        return connection


def test_repo_finds_users_by_username_and_id_with_bound_parameters() -> None:
    engine = FakeEngine()
    repo = MysqlAdminAuthRepo(engine)

    by_name = repo.find_user_by_username("admin")
    by_id = repo.find_user_by_id(7)

    assert by_name is not None
    assert by_name.id == 7
    assert by_name.failed_login_count == 2
    assert by_id == by_name
    name_sql, name_params = engine.connection.executions[0]
    id_sql, id_params = engine.connection.executions[1]
    assert "username = :username" in name_sql
    assert name_params == {"username": "admin"}
    assert "id = :user_id" in id_sql
    assert id_params == {"user_id": 7}
    _assert_all_values_are_bound(engine)


def test_repo_bootstrap_insert_only_runs_when_admin_table_is_empty() -> None:
    engine = FakeEngine()
    repo = MysqlAdminAuthRepo(engine)

    assert repo.create_user_if_missing("admin", "$argon2id$new-hash")

    sql, params = engine.connection.executions[0]
    assert "INSERT IGNORE INTO weinsight_admin_user" in sql
    assert "SELECT :username, :password_hash" in " ".join(sql.split())
    assert "WHERE NOT EXISTS" in sql
    assert "SELECT 1" in sql
    assert "FROM weinsight_admin_user" in sql
    assert params == {
        "username": "admin",
        "password_hash": "$argon2id$new-hash",
    }


def test_concurrent_bootstrap_does_not_add_admin_when_owner_already_exists() -> None:
    engine = BootstrapStateEngine(["owner"])
    repo = MysqlAdminAuthRepo(engine)
    barrier = threading.Barrier(2)

    def bootstrap() -> bool:
        barrier.wait()
        return repo.create_user_if_missing("admin", "$argon2id$new-hash")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: bootstrap(), range(2)))

    assert results == [False, False]
    assert engine.usernames == ["owner"]


def test_repo_active_session_query_enforces_every_security_condition() -> None:
    engine = FakeEngine()
    repo = MysqlAdminAuthRepo(engine)

    session = repo.find_active_session("a" * 64, NOW)

    assert session is not None
    assert session.username == "admin"
    assert session.idle_expires_at == NOW + timedelta(hours=8)
    sql, params = engine.connection.executions[0]
    assert "JOIN weinsight_admin_user" in sql
    assert "token_hash = :token_hash" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at > :now" in sql
    assert "idle_expires_at > :now" in sql
    assert "enabled = 1" in sql
    assert params == {"token_hash": "a" * 64, "now": NOW}
    _assert_all_values_are_bound(engine)


def test_repo_login_failure_locks_row_and_uses_database_current_count() -> None:
    engine = FakeEngine()
    engine.connection.admin_user_row["failed_login_count"] = 4
    repo = MysqlAdminAuthRepo(engine)

    locked_until = repo.record_login_failure(
        user_id=7,
        now=NOW,
        failure_limit=5,
        lock_minutes=15,
    )

    assert locked_until == NOW + timedelta(minutes=15)
    assert engine.begin_count == 1
    assert len(engine.connection.executions) == 2
    select_sql, select_params = engine.connection.executions[0]
    update_sql, update_params = engine.connection.executions[1]
    assert "SELECT" in select_sql
    assert "failed_login_count" in select_sql
    assert "locked_until" in select_sql
    assert "FOR UPDATE" in select_sql
    assert select_params == {"user_id": 7}
    assert "failed_login_count = :failed_login_count" in update_sql
    assert "locked_until = :locked_until" in update_sql
    assert update_params == {
        "user_id": 7,
        "failed_login_count": 5,
        "locked_until": NOW + timedelta(minutes=15),
        "now": NOW,
    }


def test_repo_login_failure_preserves_existing_active_lock() -> None:
    engine = FakeEngine()
    existing_lock = NOW + timedelta(minutes=9)
    engine.connection.admin_user_row.update(
        failed_login_count=5,
        locked_until=existing_lock,
    )
    repo = MysqlAdminAuthRepo(engine)

    locked_until = repo.record_login_failure(7, NOW, 5, 15)

    assert locked_until == existing_lock
    _, update_params = engine.connection.executions[1]
    assert update_params["failed_login_count"] == 6
    assert update_params["locked_until"] == existing_lock


def test_password_update_rolls_back_when_session_revocation_fails() -> None:
    engine = PasswordTransactionEngine(fail_session_update=True)
    repo = MysqlAdminAuthRepo(engine)

    with pytest.raises(RuntimeError, match="session update failed"):
        repo.update_password_and_revoke_sessions(
            user_id=7,
            password_hash="$argon2id$changed-hash",
            now=NOW,
        )

    assert engine.begin_count == 1
    assert len(engine.connections[0].executions) == 2
    assert engine.password_hash == "$argon2id$original-hash"
    assert engine.password_changed_at is None
    assert engine.sessions_revoked_at is None


def test_password_update_and_session_revocation_commit_in_one_transaction() -> None:
    engine = PasswordTransactionEngine(fail_session_update=False)
    repo = MysqlAdminAuthRepo(engine)

    repo.update_password_and_revoke_sessions(
        user_id=7,
        password_hash="$argon2id$changed-hash",
        now=NOW,
    )

    assert engine.begin_count == 1
    assert len(engine.connections[0].executions) == 2
    assert engine.password_hash == "$argon2id$changed-hash"
    assert engine.password_changed_at == NOW
    assert engine.sessions_revoked_at == NOW


def test_repo_writes_users_sessions_and_login_state_with_bound_parameters() -> None:
    engine = FakeEngine()
    repo = MysqlAdminAuthRepo(engine)
    session = NewAdminSessionRecord(
        id="session-id",
        user_id=7,
        token_hash="a" * 64,
        csrf_token_hash="b" * 64,
        expires_at=NOW + timedelta(days=1),
        idle_expires_at=NOW + timedelta(hours=8),
        last_seen_at=NOW,
        client_ip="192.0.2.10",
        user_agent_hash="c" * 64,
    )

    assert repo.create_user_if_missing("admin", "$argon2id$new-hash")
    repo.record_login_failure(7, NOW, 5, 15)
    repo.record_login_success(7, NOW)
    repo.update_password_and_revoke_sessions(7, "$argon2id$changed-hash", NOW)
    repo.create_session(session)
    repo.touch_session("session-id", NOW + timedelta(hours=8), NOW)
    repo.revoke_session("a" * 64, NOW)

    executions = engine.connection.executions
    assert len(executions) == 9
    create_user_sql, create_user_params = executions[0]
    assert "INSERT IGNORE INTO weinsight_admin_user" in create_user_sql
    assert create_user_params == {
        "username": "admin",
        "password_hash": "$argon2id$new-hash",
    }
    failure_select_sql, failure_select_params = executions[1]
    assert "FOR UPDATE" in failure_select_sql
    assert failure_select_params == {"user_id": 7}
    failure_sql, failure_params = executions[2]
    assert "failed_login_count = :failed_login_count" in failure_sql
    assert failure_params["failed_login_count"] == 3
    success_sql, success_params = executions[3]
    assert "failed_login_count = 0" in success_sql
    assert "locked_until = NULL" in success_sql
    assert success_params == {"user_id": 7, "now": NOW}
    password_sql, password_params = executions[4]
    assert "password_changed_at = :now" in password_sql
    assert password_params["password_hash"] == "$argon2id$changed-hash"
    revoke_all_sql, revoke_all_params = executions[5]
    assert "user_id = :user_id" in revoke_all_sql
    assert revoke_all_params == {"user_id": 7, "now": NOW}
    create_session_sql, create_session_params = executions[6]
    assert "INSERT INTO weinsight_admin_session" in create_session_sql
    assert create_session_params["token_hash"] == "a" * 64
    assert create_session_params["csrf_token_hash"] == "b" * 64
    touch_sql, touch_params = executions[7]
    assert "idle_expires_at = :idle_expires_at" in touch_sql
    assert "last_seen_at = :now" in touch_sql
    assert touch_params["session_id"] == "session-id"
    revoke_sql, revoke_params = executions[8]
    assert "token_hash = :token_hash" in revoke_sql
    assert revoke_params == {"token_hash": "a" * 64, "now": NOW}
    _assert_all_values_are_bound(engine)


def _assert_all_values_are_bound(engine: FakeEngine) -> None:
    assert engine.connection.executions
    for sql, params in engine.connection.executions:
        assert params
        for name in params:
            assert f":{name}" in sql
