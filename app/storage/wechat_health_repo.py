from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.rpa.desktop_probe import WechatHealthStatus
from app.storage.collection_event_repo import sanitize_output


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


@dataclass(frozen=True, slots=True)
class NewWechatHealthCheck:
    worker_id: str | None
    hostname: str
    status: WechatHealthStatus
    detected_version: str | None
    message: str
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class WechatHealthRecord:
    id: int
    worker_id: str | None
    hostname: str
    status: WechatHealthStatus
    detected_version: str | None
    consecutive_failure_count: int
    message: str
    checked_at: datetime


class MysqlWechatHealthRepo:
    """Persist complete health checks for one WeChat client host.

    Runtime assembly must provide one health-monitor writer per hostname (the
    collector heartbeat is that ownership boundary). Within that boundary,
    failure-count calculation and insertion share one transaction; ``FOR
    UPDATE`` also serializes overlapping writes once a host has history. The
    health-history table intentionally has no synthetic per-host lock row, so
    callers must not use this repository to bypass the single-writer contract.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_check(self, check: NewWechatHealthCheck) -> WechatHealthRecord:
        status = _validate_new_check(check)
        safe_message = sanitize_output(check.message, maximum=1000)
        safe_version = _sanitize_optional_output(
            check.detected_version, maximum=100
        )
        with self.engine.begin() as connection:
            previous_row = connection.execute(
                _SELECT_LATEST_FOR_UPDATE, {"hostname": check.hostname}
            ).mappings().first()
            previous = (
                None if previous_row is None else _record_from_row(previous_row)
            )
            if previous is not None and check.checked_at < previous.checked_at:
                raise ValueError(
                    "checked_at must not be earlier than the latest check"
                )
            previous_count = (
                0 if previous is None else previous.consecutive_failure_count
            )
            failure_count = (
                0 if status is WechatHealthStatus.OK else previous_count + 1
            )
            params = {
                "worker_id": check.worker_id,
                "hostname": check.hostname,
                "status": status.value,
                "detected_version": safe_version,
                "consecutive_failure_count": failure_count,
                "message": safe_message,
                "checked_at": _to_db_datetime(check.checked_at),
            }
            result = connection.execute(_INSERT_CHECK, params)
            record_id = _positive_integer(result.lastrowid, "id")

        return WechatHealthRecord(
            id=record_id,
            worker_id=check.worker_id,
            hostname=check.hostname,
            status=status,
            detected_version=safe_version,
            consecutive_failure_count=failure_count,
            message=safe_message,
            checked_at=check.checked_at,
        )

    def latest_check(self, hostname: str) -> WechatHealthRecord | None:
        _required_text(hostname, "hostname", 255)
        with self.engine.begin() as connection:
            row = connection.execute(
                _SELECT_LATEST, {"hostname": hostname}
            ).mappings().first()
        return None if row is None else _record_from_row(row)

    def consecutive_failure_count(self, hostname: str) -> int:
        _required_text(hostname, "hostname", 255)
        with self.engine.begin() as connection:
            row = connection.execute(
                _SELECT_FAILURE_COUNT, {"hostname": hostname}
            ).mappings().first()
        if row is None:
            return 0
        return _nonnegative_integer(
            row["consecutive_failure_count"], "consecutive_failure_count"
        )


def _validate_new_check(check: object) -> WechatHealthStatus:
    if not isinstance(check, NewWechatHealthCheck):
        raise TypeError("check must be NewWechatHealthCheck")
    _optional_text(check.worker_id, "worker_id", 100)
    _required_text(check.hostname, "hostname", 255)
    status = _health_status(check.status)
    _optional_text(check.detected_version, "detected_version", 100)
    if not isinstance(check.message, str):
        raise TypeError("message must be a string")
    _require_shanghai_datetime(check.checked_at, "checked_at")
    return status


def _record_from_row(row) -> WechatHealthRecord:
    record_id = _positive_integer(row["id"], "id")
    worker_id = row.get("worker_id")
    _optional_text(worker_id, "worker_id", 100)
    hostname = row["hostname"]
    _required_text(hostname, "hostname", 255)
    status = _health_status(row["status"])
    detected_version = row.get("detected_version")
    _optional_text(detected_version, "detected_version", 100)
    detected_version = _sanitize_optional_output(detected_version, maximum=100)
    failure_count = _nonnegative_integer(
        row["consecutive_failure_count"], "consecutive_failure_count"
    )
    raw_message = row.get("message")
    if raw_message is not None and not isinstance(raw_message, str):
        raise TypeError("message must be a string or None")
    if raw_message is not None and len(raw_message) > 1000:
        raise ValueError("message must be at most 1000 characters")
    message = "" if raw_message is None else sanitize_output(raw_message, maximum=1000)
    checked_at = _db_datetime(row["checked_at"])
    return WechatHealthRecord(
        id=record_id,
        worker_id=worker_id,
        hostname=hostname,
        status=status,
        detected_version=detected_version,
        consecutive_failure_count=failure_count,
        message=message,
        checked_at=checked_at,
    )


def _health_status(value: object) -> WechatHealthStatus:
    if isinstance(value, WechatHealthStatus):
        return value
    if not isinstance(value, str):
        raise TypeError("status must be a WechatHealthStatus or string")
    try:
        return WechatHealthStatus(value)
    except ValueError as exc:
        raise ValueError("status is invalid") from exc


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _optional_text(value: object, field: str, maximum: int) -> None:
    if value is not None:
        _required_text(value, field, maximum)


def _sanitize_optional_output(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    safe = sanitize_output(value, maximum=maximum).strip()
    return safe or None


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


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


def _to_db_datetime(value: datetime) -> datetime:
    return _require_shanghai_datetime(value, "checked_at").replace(tzinfo=None)


def _db_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database checked_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


_SELECT_COLUMNS = """
    id, worker_id, hostname, status, detected_version,
    consecutive_failure_count, message, checked_at
"""

_SELECT_LATEST = text(
    f"""
    SELECT {_SELECT_COLUMNS}
    FROM wechat_client_health_check
    WHERE hostname = :hostname
    ORDER BY checked_at DESC, id DESC
    LIMIT 1
    """
)

_SELECT_LATEST_FOR_UPDATE = text(
    f"""
    SELECT {_SELECT_COLUMNS}
    FROM wechat_client_health_check
    WHERE hostname = :hostname
    ORDER BY checked_at DESC, id DESC
    LIMIT 1
    FOR UPDATE
    """
)

_SELECT_FAILURE_COUNT = text(
    """
    SELECT consecutive_failure_count
    FROM wechat_client_health_check
    WHERE hostname = :hostname
    ORDER BY checked_at DESC, id DESC
    LIMIT 1
    """
)

_INSERT_CHECK = text(
    """
    INSERT INTO wechat_client_health_check (
        worker_id, hostname, status, detected_version,
        consecutive_failure_count, message, checked_at
    ) VALUES (
        :worker_id, :hostname, :status, :detected_version,
        :consecutive_failure_count, :message, :checked_at
    )
    """
)
