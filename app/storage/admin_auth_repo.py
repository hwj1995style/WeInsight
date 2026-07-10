from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class AdminUserRecord:
    id: int
    username: str
    password_hash: str
    enabled: bool
    password_changed_at: datetime | None
    failed_login_count: int
    locked_until: datetime | None


@dataclass(frozen=True)
class AdminSessionRecord:
    id: str
    user_id: int
    username: str
    token_hash: str
    csrf_token_hash: str
    expires_at: datetime
    idle_expires_at: datetime
    revoked_at: datetime | None
    password_changed_at: datetime | None


@dataclass(frozen=True)
class NewAdminSessionRecord:
    id: str
    user_id: int
    token_hash: str
    csrf_token_hash: str
    expires_at: datetime
    idle_expires_at: datetime
    last_seen_at: datetime
    client_ip: str
    user_agent_hash: str


class MysqlAdminAuthRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def find_user_by_username(self, username: str) -> AdminUserRecord | None:
        statement = text(
            """
            SELECT
                id,
                username,
                password_hash,
                enabled,
                password_changed_at,
                failed_login_count,
                locked_until
            FROM weinsight_admin_user
            WHERE username = :username
            """
        )
        return self._find_user(statement, {"username": username})

    def find_user_by_id(self, user_id: int) -> AdminUserRecord | None:
        statement = text(
            """
            SELECT
                id,
                username,
                password_hash,
                enabled,
                password_changed_at,
                failed_login_count,
                locked_until
            FROM weinsight_admin_user
            WHERE id = :user_id
            """
        )
        return self._find_user(statement, {"user_id": user_id})

    def create_user_if_missing(self, username: str, password_hash: str) -> bool:
        statement = text(
            """
            INSERT IGNORE INTO weinsight_admin_user (
                username,
                password_hash
            ) VALUES (
                :username,
                :password_hash
            )
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {"username": username, "password_hash": password_hash},
            )
        return bool(result.rowcount)

    def record_login_failure(
        self, user_id: int, locked_until: datetime | None
    ) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_user
            SET failed_login_count = failed_login_count + 1,
                locked_until = :locked_until,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :user_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {"user_id": user_id, "locked_until": locked_until},
            )

    def record_login_success(self, user_id: int, now: datetime) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_user
            SET failed_login_count = 0,
                locked_until = NULL,
                last_login_at = :now,
                update_time = :now
            WHERE id = :user_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"user_id": user_id, "now": now})

    def update_password(
        self, user_id: int, password_hash: str, now: datetime
    ) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_user
            SET password_hash = :password_hash,
                password_changed_at = :now,
                update_time = :now
            WHERE id = :user_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {"user_id": user_id, "password_hash": password_hash, "now": now},
            )

    def create_session(self, record: NewAdminSessionRecord) -> None:
        statement = text(
            """
            INSERT INTO weinsight_admin_session (
                id,
                user_id,
                token_hash,
                csrf_token_hash,
                expires_at,
                idle_expires_at,
                last_seen_at,
                client_ip,
                user_agent_hash
            ) VALUES (
                :id,
                :user_id,
                :token_hash,
                :csrf_token_hash,
                :expires_at,
                :idle_expires_at,
                :last_seen_at,
                :client_ip,
                :user_agent_hash
            )
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, asdict(record))

    def find_active_session(
        self, token_hash: str, now: datetime
    ) -> AdminSessionRecord | None:
        statement = text(
            """
            SELECT
                session.id,
                session.user_id,
                admin.username,
                session.token_hash,
                session.csrf_token_hash,
                session.expires_at,
                session.idle_expires_at,
                session.revoked_at,
                admin.password_changed_at
            FROM weinsight_admin_session AS session
            JOIN weinsight_admin_user AS admin
              ON admin.id = session.user_id
            WHERE session.token_hash = :token_hash
              AND session.revoked_at IS NULL
              AND session.expires_at > :now
              AND session.idle_expires_at > :now
              AND admin.enabled = 1
            """
        )
        with self.engine.begin() as connection:
            row = connection.execute(
                statement, {"token_hash": token_hash, "now": now}
            ).mappings().one_or_none()
        if row is None:
            return None
        return AdminSessionRecord(
            id=str(row["id"]),
            user_id=int(row["user_id"]),
            username=str(row["username"]),
            token_hash=str(row["token_hash"]),
            csrf_token_hash=str(row["csrf_token_hash"]),
            expires_at=row["expires_at"],
            idle_expires_at=row["idle_expires_at"],
            revoked_at=row["revoked_at"],
            password_changed_at=row["password_changed_at"],
        )

    def touch_session(
        self, session_id: str, idle_expires_at: datetime, now: datetime
    ) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_session
            SET idle_expires_at = :idle_expires_at,
                last_seen_at = :now
            WHERE id = :session_id
              AND revoked_at IS NULL
              AND expires_at > :now
              AND idle_expires_at > :now
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "session_id": session_id,
                    "idle_expires_at": idle_expires_at,
                    "now": now,
                },
            )

    def revoke_session(self, token_hash: str, now: datetime) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_session
            SET revoked_at = :now
            WHERE token_hash = :token_hash
              AND revoked_at IS NULL
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"token_hash": token_hash, "now": now})

    def revoke_user_sessions(self, user_id: int, now: datetime) -> None:
        statement = text(
            """
            UPDATE weinsight_admin_session
            SET revoked_at = :now
            WHERE user_id = :user_id
              AND revoked_at IS NULL
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"user_id": user_id, "now": now})

    def _find_user(self, statement, params: dict[str, object]) -> AdminUserRecord | None:
        with self.engine.begin() as connection:
            row = connection.execute(statement, params).mappings().one_or_none()
        if row is None:
            return None
        return AdminUserRecord(
            id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            enabled=bool(row["enabled"]),
            password_changed_at=row["password_changed_at"],
            failed_login_count=int(row["failed_login_count"] or 0),
            locked_until=row["locked_until"],
        )
