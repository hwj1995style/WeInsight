from __future__ import annotations

from datetime import datetime, timedelta

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

    def execute(self, statement, params=None):
        sql = str(statement)
        bound = dict(params or {})
        self.executions.append((sql, bound))
        if "FROM weinsight_admin_user" in sql:
            return FakeResult(
                {
                    "id": 7,
                    "username": "admin",
                    "password_hash": "$argon2id$stored-hash",
                    "enabled": 1,
                    "password_changed_at": None,
                    "failed_login_count": 2,
                    "locked_until": None,
                }
            )
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

    def begin(self):
        return self.connection


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
    repo.record_login_failure(7, NOW + timedelta(minutes=15))
    repo.record_login_success(7, NOW)
    repo.update_password(7, "$argon2id$changed-hash", NOW)
    repo.create_session(session)
    repo.touch_session("session-id", NOW + timedelta(hours=8), NOW)
    repo.revoke_session("a" * 64, NOW)
    repo.revoke_user_sessions(7, NOW)

    executions = engine.connection.executions
    assert len(executions) == 8
    create_user_sql, create_user_params = executions[0]
    assert "INSERT IGNORE INTO weinsight_admin_user" in create_user_sql
    assert create_user_params == {
        "username": "admin",
        "password_hash": "$argon2id$new-hash",
    }
    failure_sql, failure_params = executions[1]
    assert "failed_login_count = failed_login_count + 1" in failure_sql
    assert failure_params["locked_until"] == NOW + timedelta(minutes=15)
    success_sql, success_params = executions[2]
    assert "failed_login_count = 0" in success_sql
    assert "locked_until = NULL" in success_sql
    assert success_params == {"user_id": 7, "now": NOW}
    password_sql, password_params = executions[3]
    assert "password_changed_at = :now" in password_sql
    assert password_params["password_hash"] == "$argon2id$changed-hash"
    create_session_sql, create_session_params = executions[4]
    assert "INSERT INTO weinsight_admin_session" in create_session_sql
    assert create_session_params["token_hash"] == "a" * 64
    assert create_session_params["csrf_token_hash"] == "b" * 64
    touch_sql, touch_params = executions[5]
    assert "idle_expires_at = :idle_expires_at" in touch_sql
    assert "last_seen_at = :now" in touch_sql
    assert touch_params["session_id"] == "session-id"
    revoke_sql, revoke_params = executions[6]
    assert "token_hash = :token_hash" in revoke_sql
    assert revoke_params == {"token_hash": "a" * 64, "now": NOW}
    revoke_all_sql, revoke_all_params = executions[7]
    assert "user_id = :user_id" in revoke_all_sql
    assert revoke_all_params == {"user_id": 7, "now": NOW}
    _assert_all_values_are_bound(engine)


def _assert_all_values_are_bound(engine: FakeEngine) -> None:
    assert engine.connection.executions
    for sql, params in engine.connection.executions:
        assert params
        for name in params:
            assert f":{name}" in sql
