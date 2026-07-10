from __future__ import annotations

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
        params = {
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
        with self.engine.begin() as connection:
            connection.execute(_UPSERT_HEARTBEAT, params)

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
