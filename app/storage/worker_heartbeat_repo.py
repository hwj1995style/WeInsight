from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.collection_jobs import ensure_schedule_datetime
from app.storage.collection_event_repo import sanitize_output


_WORKER_TYPES = frozenset({"collector", "pipeline"})
_STATUSES = frozenset({"starting", "running", "degraded", "stopping", "stopped"})


@dataclass(frozen=True, slots=True)
class WorkerHeartbeatRecord:
    worker_id: str
    worker_type: str
    hostname: str
    process_id: int
    version: str
    status: str
    last_heartbeat_at: datetime
    start_time: datetime
    last_error_summary: str | None


class MysqlWorkerHeartbeatRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_heartbeat(self, record: WorkerHeartbeatRecord) -> None:
        _validate_record(record)
        params = _heartbeat_params(record)
        with self.engine.begin() as connection:
            connection.execute(_UPSERT_HEARTBEAT, params)

    def register_collector_start(
        self,
        record: WorkerHeartbeatRecord,
        now: datetime,
        ttl_seconds: int,
        lock_timeout_seconds: int = 0,
    ) -> bool:
        _validate_record(record)
        if record.worker_type != "collector" or record.status != "starting":
            raise ValueError(
                "startup record must be a collector in starting status"
            )
        _shanghai_datetime(now, "now")
        if record.last_heartbeat_at != now:
            raise ValueError("startup last_heartbeat_at must equal now")
        _positive_seconds(ttl_seconds, "ttl_seconds")
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, int)
            or lock_timeout_seconds < 0
        ):
            raise ValueError(
                "lock_timeout_seconds must be a nonnegative integer"
            )
        lock_name = _startup_lock_name(record.hostname)
        acquired = False
        with self.engine.connect() as connection:
            try:
                acquired = (
                    connection.execute(
                        _GET_STARTUP_LOCK,
                        {
                            "lock_name": lock_name,
                            "lock_timeout_seconds": lock_timeout_seconds,
                        },
                    ).scalar_one()
                    == 1
                )
                if not acquired:
                    connection.rollback()
                    return False
                live = bool(
                    connection.execute(
                        _LIVE_COLLECTOR_FOR_STARTUP,
                        {
                            "hostname": record.hostname,
                            "cutoff": _to_db_datetime(
                                now - timedelta(seconds=ttl_seconds)
                            ),
                        },
                    ).scalar_one()
                )
                if live:
                    connection.commit()
                    return False
                connection.execute(
                    _UPSERT_HEARTBEAT,
                    _heartbeat_params(record),
                )
                # The starting heartbeat must be committed while the advisory
                # lock is still held, otherwise a peer can miss the row.
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise
            finally:
                if acquired:
                    connection.execute(
                        _RELEASE_STARTUP_LOCK,
                        {"lock_name": lock_name},
                    )
                    connection.commit()

    def has_live_collector(
        self,
        hostname: str,
        now: datetime,
        ttl_seconds: int,
        exclude_worker_id: str | None = None,
    ) -> bool:
        _required_text(hostname, "hostname", 255)
        _shanghai_datetime(now, "now")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be a positive integer")
        if exclude_worker_id is not None:
            _required_text(exclude_worker_id, "exclude_worker_id", 100)
        exclude = (
            "" if exclude_worker_id is None else "AND worker_id <> :exclude_worker_id"
        )
        params = {
            "hostname": hostname,
            "cutoff": _to_db_datetime(now - timedelta(seconds=ttl_seconds)),
        }
        if exclude_worker_id is not None:
            params["exclude_worker_id"] = exclude_worker_id
        statement = text(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM wechat_worker_heartbeat
                WHERE worker_type = 'collector'
                  AND hostname = :hostname
                  AND status IN ('starting', 'running', 'degraded', 'stopping')
                  AND last_heartbeat_at >= :cutoff
                  {exclude}
                LIMIT 1
            )
            """
        )
        with self.engine.begin() as connection:
            return bool(connection.execute(statement, params).scalar_one())


def _validate_record(record: object) -> None:
    if not isinstance(record, WorkerHeartbeatRecord):
        raise TypeError("record must be WorkerHeartbeatRecord")
    _required_text(record.worker_id, "worker_id", 100)
    if record.worker_type not in _WORKER_TYPES:
        raise ValueError("worker_type must be collector or pipeline")
    _required_text(record.hostname, "hostname", 255)
    if (
        isinstance(record.process_id, bool)
        or not isinstance(record.process_id, int)
        or record.process_id < 1
    ):
        raise ValueError("process_id must be a positive integer")
    _required_text(record.version, "version", 100)
    if record.status not in _STATUSES:
        raise ValueError("status is invalid")
    _shanghai_datetime(record.last_heartbeat_at, "last_heartbeat_at")
    _shanghai_datetime(record.start_time, "start_time")
    if record.start_time > record.last_heartbeat_at:
        raise ValueError("start_time must not be after last_heartbeat_at")
    if record.last_error_summary is not None and not isinstance(
        record.last_error_summary, str
    ):
        raise TypeError("last_error_summary must be a string or None")


def _heartbeat_params(record: WorkerHeartbeatRecord) -> dict[str, object]:
    return {
        "worker_id": record.worker_id,
        "worker_type": record.worker_type,
        "hostname": record.hostname,
        "process_id": record.process_id,
        "version": record.version,
        "status": record.status,
        "last_heartbeat_at": _to_db_datetime(record.last_heartbeat_at),
        "start_time": _to_db_datetime(record.start_time),
        "last_error_summary": (
            None
            if record.last_error_summary is None
            else sanitize_output(record.last_error_summary)
        ),
    }


def _positive_seconds(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _startup_lock_name(hostname: str) -> str:
    digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:32]
    return f"weinsight:collector-start:{digest}"


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _shanghai_datetime(value: object, field: str) -> None:
    ensure_schedule_datetime(value, field_name=field)


def _to_db_datetime(value: datetime) -> datetime:
    _shanghai_datetime(value, "datetime")
    return value.replace(tzinfo=None)


_UPSERT_HEARTBEAT = text(
    """
    INSERT INTO wechat_worker_heartbeat (
        worker_id, worker_type, hostname, process_id, version, status,
        last_heartbeat_at, start_time, last_error_summary
    ) VALUES (
        :worker_id, :worker_type, :hostname, :process_id, :version, :status,
        :last_heartbeat_at, :start_time, :last_error_summary
    )
    ON DUPLICATE KEY UPDATE
        worker_type = VALUES(worker_type),
        hostname = VALUES(hostname),
        process_id = VALUES(process_id),
        version = VALUES(version),
        status = VALUES(status),
        last_heartbeat_at = VALUES(last_heartbeat_at),
        last_error_summary = VALUES(last_error_summary)
    """
)

_GET_STARTUP_LOCK = text(
    """
    SELECT GET_LOCK(:lock_name, :lock_timeout_seconds)
    """
)

_LIVE_COLLECTOR_FOR_STARTUP = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM wechat_worker_heartbeat
        WHERE worker_type = 'collector'
          AND hostname = :hostname
          AND status IN ('starting', 'running', 'degraded', 'stopping')
          AND last_heartbeat_at >= :cutoff
        LIMIT 1
    )
    """
)

_RELEASE_STARTUP_LOCK = text(
    """
    SELECT RELEASE_LOCK(:lock_name)
    """
)
