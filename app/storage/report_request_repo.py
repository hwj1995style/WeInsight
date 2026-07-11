from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.domain.report_lifecycle import GenerationTrigger
from app.storage.collection_event_repo import sanitize_output


_ZONE = ZoneInfo("Asia/Shanghai")
_REQUEST_TRIGGERS = frozenset(
    {
        GenerationTrigger.MANUAL,
        GenerationTrigger.AUTOMATIC,
        GenerationTrigger.COMPENSATION,
    }
)


class ReportRequestConflictError(RuntimeError):
    pass


class ReportRequestStateError(RuntimeError):
    pass


class ReportType(str, Enum):
    GROUP = "group"
    ARTICLE = "article"
    SUMMARY = "summary"
    ALL = "all"


class ReportRequestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NewReportRequest:
    idempotency_key: str
    report_type: ReportType
    report_date: date
    source_name: str | None
    generation_trigger: GenerationTrigger
    data_cutoff_time: datetime
    requested_by: str

    def __post_init__(self) -> None:
        _validate_request_payload(self)
        object.__setattr__(
            self,
            "idempotency_key",
            _normalized_text(self.idempotency_key, "idempotency_key", 100),
        )
        object.__setattr__(
            self,
            "requested_by",
            _normalized_text(self.requested_by, "requested_by", 100),
        )
        if self.source_name is not None:
            object.__setattr__(
                self,
                "source_name",
                _normalized_text(self.source_name, "source_name", 200),
            )


@dataclass(frozen=True, slots=True)
class ReportRequest:
    id: int
    idempotency_key: str
    report_type: ReportType
    report_date: date
    source_name: str | None
    generation_trigger: GenerationTrigger
    data_cutoff_time: datetime
    requested_by: str
    status: ReportRequestStatus
    worker_id: str | None
    lease_expires_at: datetime | None
    error_summary: str | None
    create_time: datetime
    start_time: datetime | None
    end_time: datetime | None

    def __post_init__(self) -> None:
        payload = NewReportRequest(
            idempotency_key=self.idempotency_key,
            report_type=self.report_type,
            report_date=self.report_date,
            source_name=self.source_name,
            generation_trigger=self.generation_trigger,
            data_cutoff_time=self.data_cutoff_time,
            requested_by=self.requested_by,
        )
        object.__setattr__(self, "idempotency_key", payload.idempotency_key)
        object.__setattr__(self, "source_name", payload.source_name)
        object.__setattr__(self, "requested_by", payload.requested_by)
        if self.worker_id is not None:
            object.__setattr__(
                self,
                "worker_id",
                _normalized_text(self.worker_id, "worker_id", 100),
            )
        if self.error_summary is not None:
            if not isinstance(self.error_summary, str):
                raise ValueError("error_summary must be a string or None")
            object.__setattr__(
                self,
                "error_summary",
                _safe_error_summary(self.error_summary),
            )
        self.validate()

    def validate(self) -> None:
        _validate_report_request(self)


class MysqlReportRequestRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_or_get(self, request: NewReportRequest) -> int:
        if not isinstance(request, NewReportRequest):
            raise TypeError("request must be NewReportRequest")
        params = _new_request_params(request)
        try:
            with self.engine.begin() as connection:
                result = connection.execute(_INSERT_REQUEST, params)
            return int(result.lastrowid)
        except IntegrityError as exc:
            if not _is_idempotency_duplicate(exc):
                raise
            duplicate_error = exc

        with self.engine.begin() as connection:
            row = connection.execute(
                _SELECT_BY_IDEMPOTENCY_KEY_FOR_UPDATE,
                {"idempotency_key": request.idempotency_key},
            ).mappings().first()
            if row is None:
                raise ReportRequestStateError(
                    "duplicate request could not be resolved"
                ) from duplicate_error
            if not _immutable_payload_matches(row, request):
                raise ReportRequestConflictError(
                    "idempotency key conflicts with an existing request payload"
                ) from duplicate_error
            return int(row["id"])

    def claim_next(
        self,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ) -> ReportRequest | None:
        db_now = _to_db_datetime(now)
        normalized_worker_id = _normalized_text(worker_id, "worker_id", 100)
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds < 1
        ):
            raise ValueError("lease_seconds must be a positive integer")
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.recover_expired(now)
        with self.engine.begin() as connection:
            row = connection.execute(_LOCK_NEXT_PENDING, {}).mappings().first()
            if row is None:
                return None
            result = connection.execute(
                _CLAIM_REQUEST,
                {
                    "request_id": int(row["id"]),
                    "worker_id": normalized_worker_id,
                    "now": db_now,
                    "lease_expires_at": _to_db_datetime(lease_expires_at),
                },
            )
            if int(result.rowcount or 0) != 1:
                raise ReportRequestStateError(
                    "report request is no longer pending"
                )
            claimed_row = dict(row)
            claimed_row.update(
                {
                    "status": ReportRequestStatus.RUNNING.value,
                    "worker_id": normalized_worker_id,
                    "start_time": db_now,
                    "lease_expires_at": _to_db_datetime(lease_expires_at),
                }
            )
            return _request_from_row(claimed_row)

    def recover_expired(self, now: datetime) -> int:
        db_now = _to_db_datetime(now)
        with self.engine.begin() as connection:
            result = connection.execute(_RECOVER_EXPIRED, {"now": db_now})
            return int(result.rowcount or 0)

    def mark_success(self, request_id: int, now: datetime) -> None:
        self._mark_terminal(request_id, now, _MARK_SUCCESS, None)

    def mark_partial_success(
        self,
        request_id: int,
        error_summary: str,
        now: datetime,
    ) -> None:
        self._mark_terminal(
            request_id,
            now,
            _MARK_PARTIAL_SUCCESS,
            _safe_error_summary(error_summary),
        )

    def mark_failed(
        self,
        request_id: int,
        error_summary: str,
        now: datetime,
    ) -> None:
        self._mark_terminal(
            request_id,
            now,
            _MARK_FAILED,
            _safe_error_summary(error_summary),
        )

    def mark_success_owned(
        self,
        request: ReportRequest,
        now: datetime,
    ) -> None:
        self._mark_terminal_owned(request, now, _MARK_SUCCESS_OWNED, None)

    def mark_partial_success_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        self._mark_terminal_owned(
            request,
            now,
            _MARK_PARTIAL_SUCCESS_OWNED,
            _safe_error_summary(error_summary),
        )

    def mark_failed_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        self._mark_terminal_owned(
            request,
            now,
            _MARK_FAILED_OWNED,
            _safe_error_summary(error_summary),
        )

    def get_request(self, request_id: int) -> ReportRequest | None:
        _positive_id(request_id, "request_id")
        with self.engine.begin() as connection:
            row = connection.execute(
                _SELECT_BY_ID,
                {"request_id": request_id},
            ).mappings().first()
        return None if row is None else _request_from_row(row)

    def _mark_terminal(
        self,
        request_id: int,
        now: datetime,
        statement,
        error_summary: str | None,
    ) -> None:
        _positive_id(request_id, "request_id")
        db_now = _to_db_datetime(now)
        params = {"request_id": request_id, "now": db_now}
        if error_summary is not None:
            params["error_summary"] = error_summary
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            if int(result.rowcount or 0) != 1:
                raise ReportRequestStateError(
                    "report request is not running"
                )

    def _mark_terminal_owned(
        self,
        request: ReportRequest,
        now: datetime,
        statement,
        error_summary: str | None,
    ) -> None:
        if not isinstance(request, ReportRequest):
            raise TypeError("request must be ReportRequest")
        request.validate()
        if request.status is not ReportRequestStatus.RUNNING:
            raise ReportRequestStateError("report request is not running")
        if (
            request.worker_id is None
            or request.start_time is None
            or request.lease_expires_at is None
        ):
            raise ReportRequestStateError("report request claim identity is incomplete")
        db_now = _to_db_datetime(now)
        if request.lease_expires_at <= now:
            raise ReportRequestStateError("report request claim lease is expired")
        params = {
            "request_id": request.id,
            "worker_id": request.worker_id,
            "start_time": _to_db_datetime(request.start_time),
            "expected_lease_expires_at": _to_db_datetime(
                request.lease_expires_at
            ),
            "now": db_now,
        }
        if error_summary is not None:
            params["error_summary"] = error_summary
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            if int(result.rowcount or 0) != 1:
                raise ReportRequestStateError(
                    "report request is not owned by the current claim"
                )


def _validate_request_payload(request: NewReportRequest) -> None:
    if not isinstance(request.report_type, ReportType):
        raise ValueError("report_type must be a ReportType")
    if not isinstance(request.report_date, date) or isinstance(
        request.report_date, datetime
    ):
        raise ValueError("report_date must be a calendar date")
    if (
        not isinstance(request.generation_trigger, GenerationTrigger)
        or request.generation_trigger not in _REQUEST_TRIGGERS
    ):
        raise ValueError("generation_trigger is invalid for a report request")
    _shanghai_datetime(request.data_cutoff_time, "data_cutoff_time")
    _normalized_text(request.idempotency_key, "idempotency_key", 100)
    _normalized_text(request.requested_by, "requested_by", 100)
    if request.report_type in {ReportType.SUMMARY, ReportType.ALL}:
        if request.source_name is not None:
            raise ValueError("source_name must be empty for summary or all")
    elif request.source_name is not None:
        _normalized_text(request.source_name, "source_name", 200)


def _normalized_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{field} must not contain control characters")
    return normalized


def _shanghai_datetime(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != "Asia/Shanghai"
    ):
        raise ValueError(f"{field} must use Asia/Shanghai ZoneInfo")
    return value


def _to_db_datetime(value: datetime) -> datetime:
    return _shanghai_datetime(value, "datetime").replace(tzinfo=None)


def _db_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a database datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


def _optional_db_datetime(value: object, field: str) -> datetime | None:
    return None if value is None else _db_datetime(value, field)


def _positive_id(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _safe_error_summary(value: str) -> str:
    safe = sanitize_output(value, maximum=500).strip()
    return safe or "report generation failed"


def _new_request_params(request: NewReportRequest) -> dict[str, object]:
    return {
        "idempotency_key": request.idempotency_key,
        "report_type": request.report_type.value,
        "report_date": request.report_date,
        "source_name": request.source_name,
        "generation_trigger": request.generation_trigger.value,
        "data_cutoff_time": _to_db_datetime(request.data_cutoff_time),
        "requested_by": request.requested_by,
    }


def _is_idempotency_duplicate(error: IntegrityError) -> bool:
    arguments = getattr(error.orig, "args", ())
    return (
        len(arguments) >= 2
        and arguments[0] == 1062
        and "uk_report_request_idempotency" in str(arguments[1])
    )


def _immutable_payload_matches(row, request: NewReportRequest) -> bool:
    return all(
        (
            row["report_type"] == request.report_type.value,
            row["report_date"] == request.report_date,
            row["source_name"] == request.source_name,
            row["generation_trigger"] == request.generation_trigger.value,
            row["data_cutoff_time"] == _to_db_datetime(request.data_cutoff_time),
            row["requested_by"] == request.requested_by,
        )
    )


def _request_from_row(row) -> ReportRequest:
    try:
        report_type = ReportType(str(row["report_type"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid report_type in report request") from exc
    try:
        generation_trigger = GenerationTrigger(str(row["generation_trigger"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid generation_trigger in report request") from exc
    try:
        status = ReportRequestStatus(str(row["status"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid status in report request") from exc
    payload = NewReportRequest(
        idempotency_key=row["idempotency_key"],
        report_type=report_type,
        report_date=row["report_date"],
        source_name=row["source_name"],
        generation_trigger=generation_trigger,
        data_cutoff_time=_db_datetime(row["data_cutoff_time"], "data_cutoff_time"),
        requested_by=row["requested_by"],
    )
    worker_id = (
        None
        if row["worker_id"] is None
        else _normalized_text(row["worker_id"], "worker_id", 100)
    )
    error_summary = row["error_summary"]
    if error_summary is not None:
        if not isinstance(error_summary, str):
            raise ValueError("invalid error_summary in report request")
        error_summary = _safe_error_summary(error_summary)
    request = ReportRequest(
        id=_positive_id(int(row["id"]), "id"),
        idempotency_key=payload.idempotency_key,
        report_type=payload.report_type,
        report_date=payload.report_date,
        source_name=payload.source_name,
        generation_trigger=payload.generation_trigger,
        data_cutoff_time=payload.data_cutoff_time,
        requested_by=payload.requested_by,
        status=status,
        worker_id=worker_id,
        lease_expires_at=_optional_db_datetime(
            row["lease_expires_at"], "lease_expires_at"
        ),
        error_summary=error_summary,
        create_time=_db_datetime(row["create_time"], "create_time"),
        start_time=_optional_db_datetime(row["start_time"], "start_time"),
        end_time=_optional_db_datetime(row["end_time"], "end_time"),
    )
    return request


def _validate_request_state(request: ReportRequest) -> None:
    if request.status is ReportRequestStatus.PENDING:
        if any(
            value is not None
            for value in (
                request.worker_id,
                request.lease_expires_at,
                request.start_time,
                request.end_time,
            )
        ):
            raise ValueError("pending report request has running state")
        return
    if request.status is ReportRequestStatus.RUNNING:
        if (
            request.worker_id is None
            or request.lease_expires_at is None
            or request.start_time is None
            or request.end_time is not None
        ):
            raise ValueError("running report request state is incomplete")
        return
    if request.lease_expires_at is not None or request.end_time is None:
        raise ValueError("terminal report request state is incomplete")


def _validate_report_request(request: ReportRequest) -> None:
    _positive_id(request.id, "id")
    payload = NewReportRequest(
        idempotency_key=request.idempotency_key,
        report_type=request.report_type,
        report_date=request.report_date,
        source_name=request.source_name,
        generation_trigger=request.generation_trigger,
        data_cutoff_time=request.data_cutoff_time,
        requested_by=request.requested_by,
    )
    if (
        request.idempotency_key != payload.idempotency_key
        or request.source_name != payload.source_name
        or request.requested_by != payload.requested_by
    ):
        raise ValueError("report request text fields are not normalized")
    if not isinstance(request.status, ReportRequestStatus):
        raise ValueError("status must be a ReportRequestStatus")
    _shanghai_datetime(request.create_time, "create_time")
    if request.worker_id is not None:
        normalized_worker_id = _normalized_text(
            request.worker_id,
            "worker_id",
            100,
        )
        if request.worker_id != normalized_worker_id:
            raise ValueError("worker_id must be normalized")
    for field in ("lease_expires_at", "start_time", "end_time"):
        value = getattr(request, field)
        if value is not None:
            _shanghai_datetime(value, field)
    if request.error_summary is not None:
        if not isinstance(request.error_summary, str):
            raise ValueError("error_summary must be a string or None")
        if request.error_summary != _safe_error_summary(request.error_summary):
            raise ValueError("error_summary must be safe and at most 500 characters")
    _validate_request_state(request)


_INSERT_REQUEST = text(
    """
    INSERT INTO wechat_report_generation_request (
        idempotency_key, report_type, report_date, source_name,
        generation_trigger, data_cutoff_time, requested_by
    ) VALUES (
        :idempotency_key, :report_type, :report_date, :source_name,
        :generation_trigger, :data_cutoff_time, :requested_by
    )
    """
)


_SELECT_BY_IDEMPOTENCY_KEY_FOR_UPDATE = text(
    """
    SELECT
        id, idempotency_key, report_type, report_date, source_name,
        generation_trigger, data_cutoff_time, requested_by
    FROM wechat_report_generation_request
    WHERE idempotency_key = :idempotency_key
    LIMIT 1
    FOR UPDATE
    """
)


_REQUEST_COLUMNS = """
    id, idempotency_key, report_type, report_date, source_name,
    generation_trigger, data_cutoff_time, requested_by, status,
    worker_id, lease_expires_at, error_summary, create_time,
    start_time, end_time
"""


_RECOVER_EXPIRED = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'pending', worker_id = NULL, lease_expires_at = NULL,
        start_time = NULL, end_time = NULL, error_summary = NULL
    WHERE status = 'running'
      AND lease_expires_at <= :now
    """
)


_LOCK_NEXT_PENDING = text(
    f"""
    SELECT {_REQUEST_COLUMNS}
    FROM wechat_report_generation_request
    WHERE status = 'pending'
    ORDER BY create_time ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
    """
)


_CLAIM_REQUEST = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'running', worker_id = :worker_id,
        start_time = :now, lease_expires_at = :lease_expires_at,
        end_time = NULL, error_summary = NULL
    WHERE id = :request_id
      AND status = 'pending'
    """
)


_MARK_SUCCESS = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'success', end_time = :now,
        lease_expires_at = NULL, error_summary = NULL
    WHERE id = :request_id
      AND status = 'running'
    """
)


_MARK_PARTIAL_SUCCESS = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'partial_success', end_time = :now,
        lease_expires_at = NULL, error_summary = :error_summary
    WHERE id = :request_id
      AND status = 'running'
    """
)


_MARK_FAILED = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'failed', end_time = :now,
        lease_expires_at = NULL, error_summary = :error_summary
    WHERE id = :request_id
      AND status = 'running'
    """
)


_MARK_SUCCESS_OWNED = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'success', end_time = :now,
        lease_expires_at = NULL, error_summary = NULL
    WHERE id = :request_id
      AND status = 'running'
      AND worker_id = :worker_id
      AND start_time = :start_time
      AND lease_expires_at = :expected_lease_expires_at
      AND lease_expires_at > :now
    """
)


_MARK_PARTIAL_SUCCESS_OWNED = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'partial_success', end_time = :now,
        lease_expires_at = NULL, error_summary = :error_summary
    WHERE id = :request_id
      AND status = 'running'
      AND worker_id = :worker_id
      AND start_time = :start_time
      AND lease_expires_at = :expected_lease_expires_at
      AND lease_expires_at > :now
    """
)


_MARK_FAILED_OWNED = text(
    """
    UPDATE wechat_report_generation_request
    SET status = 'failed', end_time = :now,
        lease_expires_at = NULL, error_summary = :error_summary
    WHERE id = :request_id
      AND status = 'running'
      AND worker_id = :worker_id
      AND start_time = :start_time
      AND lease_expires_at = :expected_lease_expires_at
      AND lease_expires_at > :now
    """
)


_SELECT_BY_ID = text(
    f"""
    SELECT {_REQUEST_COLUMNS}
    FROM wechat_report_generation_request
    WHERE id = :request_id
    LIMIT 1
    """
)
