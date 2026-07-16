from __future__ import annotations

from datetime import datetime, timedelta
import json

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.werss_authorization import (
    AuthorizationNotice,
    AuthorizationManagementSettings,
    WeRSSAuthorizationSnapshot,
)


class MysqlWeRSSAuthorizationRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_state(self) -> WeRSSAuthorizationSnapshot | None:
        with self.engine.begin() as connection:
            row = connection.execute(_SELECT_STATE).mappings().first()
        if row is None:
            return None
        return WeRSSAuthorizationSnapshot(
            status=row["status"],
            account_name=row["account_name"],
            expires_at=row["expires_at"],
            last_checked_at=row["last_checked_at"],
            last_successful_check_at=row["last_successful_check_at"],
            last_error_code=row["last_error_code"],
            authorization_version=row["authorization_version"],
        )

    def get_settings(self) -> AuthorizationManagementSettings | None:
        with self.engine.begin() as connection:
            row = connection.execute(_SELECT_SETTINGS).mappings().first()
        if row is None:
            return None
        try:
            recipients = json.loads(row["recipients_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            recipients = []
        if not isinstance(recipients, list) or not all(isinstance(item, str) for item in recipients):
            recipients = []
        return AuthorizationManagementSettings(
            werss_username=row["werss_username"],
            werss_password_encrypted=row["werss_password_encrypted"],
            smtp_enabled=bool(row["smtp_enabled"]),
            smtp_host=row["smtp_host"],
            smtp_port=int(row["smtp_port"]),
            smtp_username=row["smtp_username"],
            smtp_password_encrypted=row["smtp_password_encrypted"],
            smtp_security=row["smtp_security"],
            from_address=row["from_address"],
            recipients=tuple(recipients),
            updated_at=row["updated_at"],
        )

    def upsert_settings(self, settings: AuthorizationManagementSettings) -> None:
        with self.engine.begin() as connection:
            connection.execute(_UPSERT_SETTINGS, {
                "werss_username": settings.werss_username,
                "werss_password_encrypted": settings.werss_password_encrypted,
                "smtp_enabled": settings.smtp_enabled,
                "smtp_host": settings.smtp_host,
                "smtp_port": settings.smtp_port,
                "smtp_username": settings.smtp_username,
                "smtp_password_encrypted": settings.smtp_password_encrypted,
                "smtp_security": settings.smtp_security,
                "from_address": settings.from_address,
                "recipients_json": json.dumps(settings.recipients, ensure_ascii=False, separators=(",", ":")),
                "updated_at": settings.updated_at,
            })

    def upsert_state(self, snapshot: WeRSSAuthorizationSnapshot) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                _UPSERT_STATE,
                {
                    "status": snapshot.status,
                    "account_name": snapshot.account_name,
                    "expires_at": snapshot.expires_at,
                    "last_checked_at": snapshot.last_checked_at,
                    "last_successful_check_at": snapshot.last_successful_check_at,
                    "last_error_code": snapshot.last_error_code,
                    "authorization_version": snapshot.authorization_version,
                    "updated_at": snapshot.last_checked_at,
                },
            )

    def ensure_notice(
        self,
        snapshot: WeRSSAuthorizationSnapshot,
        notice_type: str,
        recipient_count: int,
    ) -> None:
        if snapshot.authorization_version is None:
            return
        with self.engine.begin() as connection:
            connection.execute(
                _INSERT_NOTICE,
                {
                    "authorization_version": snapshot.authorization_version,
                    "notice_type": notice_type,
                    "recipient_count": recipient_count,
                    "now": snapshot.last_checked_at,
                },
            )

    def claim_due_notice(self, now: datetime) -> AuthorizationNotice | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                _SELECT_DUE_NOTICE, {"now": now}
            ).mappings().first()
            if row is None:
                return None
            connection.execute(
                _MARK_SENDING,
                {"id": row["id"], "now": now},
            )
        return AuthorizationNotice(
            id=int(row["id"]),
            authorization_version=row["authorization_version"],
            notice_type=row["notice_type"],
            attempt_count=int(row["attempt_count"]) + 1,
        )

    def mark_notice_sent(self, notice_id: int, now: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(_MARK_SENT, {"id": notice_id, "now": now})

    def mark_notice_retry(
        self,
        notice_id: int,
        now: datetime,
        error_code: str,
        attempt_count: int,
    ) -> None:
        delays = {1: 5, 2: 15}
        terminal = attempt_count >= 3
        with self.engine.begin() as connection:
            connection.execute(
                _MARK_RETRY,
                {
                    "id": notice_id,
                    "status": "failed" if terminal else "retry_wait",
                    "next_attempt_at": None if terminal else now + timedelta(minutes=delays.get(attempt_count, 60)),
                    "error_code": error_code[:100],
                    "now": now,
                },
            )


_SELECT_STATE = text("""
SELECT status, account_name, expires_at, last_checked_at,
       last_successful_check_at, last_error_code, authorization_version
FROM wechat_werss_authorization_state
WHERE singleton_id = 1
""")

_SELECT_SETTINGS = text("""
SELECT werss_username, werss_password_encrypted, smtp_enabled, smtp_host,
       smtp_port, smtp_username, smtp_password_encrypted, smtp_security,
       from_address, recipients_json, updated_at
FROM wechat_werss_authorization_settings
WHERE singleton_id = 1
""")

_UPSERT_SETTINGS = text("""
INSERT INTO wechat_werss_authorization_settings (
    singleton_id, werss_username, werss_password_encrypted, smtp_enabled,
    smtp_host, smtp_port, smtp_username, smtp_password_encrypted,
    smtp_security, from_address, recipients_json, updated_at
) VALUES (
    1, :werss_username, :werss_password_encrypted, :smtp_enabled,
    :smtp_host, :smtp_port, :smtp_username, :smtp_password_encrypted,
    :smtp_security, :from_address, :recipients_json, :updated_at
)
ON DUPLICATE KEY UPDATE
    werss_username = VALUES(werss_username),
    werss_password_encrypted = VALUES(werss_password_encrypted),
    smtp_enabled = VALUES(smtp_enabled), smtp_host = VALUES(smtp_host),
    smtp_port = VALUES(smtp_port), smtp_username = VALUES(smtp_username),
    smtp_password_encrypted = VALUES(smtp_password_encrypted),
    smtp_security = VALUES(smtp_security), from_address = VALUES(from_address),
    recipients_json = VALUES(recipients_json), updated_at = VALUES(updated_at)
""")

_UPSERT_STATE = text("""
INSERT INTO wechat_werss_authorization_state (
    singleton_id, status, account_name, expires_at, last_checked_at,
    last_successful_check_at, last_error_code, authorization_version, updated_at
) VALUES (
    1, :status, :account_name, :expires_at, :last_checked_at,
    :last_successful_check_at, :last_error_code, :authorization_version, :updated_at
)
ON DUPLICATE KEY UPDATE
    status = VALUES(status), account_name = VALUES(account_name),
    expires_at = VALUES(expires_at), last_checked_at = VALUES(last_checked_at),
    last_successful_check_at = VALUES(last_successful_check_at),
    last_error_code = VALUES(last_error_code),
    authorization_version = VALUES(authorization_version), updated_at = VALUES(updated_at)
""")

_INSERT_NOTICE = text("""
INSERT IGNORE INTO wechat_werss_authorization_notice (
    authorization_version, notice_type, status, attempt_count,
    next_attempt_at, recipient_count, create_time, update_time
) VALUES (
    :authorization_version, :notice_type, 'pending', 0,
    :now, :recipient_count, :now, :now
)
""")

_SELECT_DUE_NOTICE = text("""
SELECT id, authorization_version, notice_type, attempt_count
FROM wechat_werss_authorization_notice
WHERE status IN ('pending', 'retry_wait') AND next_attempt_at <= :now
ORDER BY id ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
""")

_MARK_SENDING = text("""
UPDATE wechat_werss_authorization_notice
SET status = 'sending', attempt_count = attempt_count + 1, update_time = :now
WHERE id = :id
""")

_MARK_SENT = text("""
UPDATE wechat_werss_authorization_notice
SET status = 'sent', sent_at = :now, last_error_code = NULL, update_time = :now
WHERE id = :id
""")

_MARK_RETRY = text("""
UPDATE wechat_werss_authorization_notice
SET status = :status, next_attempt_at = :next_attempt_at,
    last_error_code = :error_code, update_time = :now
WHERE id = :id
""")
