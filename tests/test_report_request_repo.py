from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.report_lifecycle import GenerationTrigger
from app.storage.report_request_repo import (
    MysqlReportRequestRepo,
    NewReportRequest,
    ReportRequest,
    ReportRequestConflictError,
    ReportRequestStateError,
    ReportRequestStatus,
    ReportType,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 15, 30, tzinfo=ZONE)


class Result:
    def __init__(self, *, rows=None, rowcount: int = 1, lastrowid: int | None = None) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, results) -> None:
        self.connection = Connection(results)
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


def new_request(**changes) -> NewReportRequest:
    values = {
        "idempotency_key": "manual-form-1",
        "report_type": ReportType.GROUP,
        "report_date": date(2026, 7, 10),
        "source_name": "核心群A",
        "generation_trigger": GenerationTrigger.MANUAL,
        "data_cutoff_time": NOW,
        "requested_by": "admin",
    }
    values.update(changes)
    return NewReportRequest(**values)


def matching_row(**changes) -> dict[str, object]:
    row = {
        "id": 41,
        "idempotency_key": "manual-form-1",
        "report_type": "group",
        "report_date": date(2026, 7, 10),
        "source_name": "核心群A",
        "generation_trigger": "manual",
        "data_cutoff_time": datetime(2026, 7, 10, 15, 30),
        "requested_by": "admin",
    }
    row.update(changes)
    return row


def request_row(**changes) -> dict[str, object]:
    row = {
        **matching_row(),
        "status": "pending",
        "worker_id": None,
        "lease_expires_at": None,
        "error_summary": None,
        "create_time": datetime(2026, 7, 10, 15, 30),
        "start_time": None,
        "end_time": None,
    }
    row.update(changes)
    return row


def mysql_integrity_error(code: int, message: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(code, message))


def running_request(**changes) -> ReportRequest:
    values = {
        "id": 41,
        "idempotency_key": "manual-form-1",
        "report_type": ReportType.GROUP,
        "report_date": date(2026, 7, 10),
        "source_name": "核心群A",
        "generation_trigger": GenerationTrigger.MANUAL,
        "data_cutoff_time": NOW,
        "requested_by": "admin",
        "status": ReportRequestStatus.RUNNING,
        "worker_id": "pipeline-1",
        "lease_expires_at": NOW + timedelta(minutes=2),
        "error_summary": None,
        "create_time": NOW,
        "start_time": NOW,
        "end_time": None,
    }
    values.update(changes)
    return ReportRequest(**values)


def test_new_report_request_normalizes_text_fields() -> None:
    request = new_request(
        idempotency_key=" manual-form-1 ",
        source_name=" 核心群A ",
        requested_by=" admin ",
    )

    assert request.idempotency_key == "manual-form-1"
    assert request.source_name == "核心群A"
    assert request.requested_by == "admin"


@pytest.mark.parametrize(
    "changes",
    [
        {"report_type": "group"},
        {"report_type": ReportType.ALL, "source_name": "核心群A"},
        {"report_type": ReportType.GROUP, "source_name": "   "},
        {"generation_trigger": GenerationTrigger.LEGACY},
        {"data_cutoff_time": NOW.replace(tzinfo=None)},
        {"requested_by": "admin\nroot"},
        {"idempotency_key": "k" * 101},
    ],
)
def test_new_report_request_rejects_invalid_payload(changes) -> None:
    with pytest.raises(ValueError):
        new_request(**changes)


def test_create_or_get_inserts_bound_payload_and_returns_new_id() -> None:
    engine = Engine([Result(lastrowid=41)])
    repo = MysqlReportRequestRepo(engine)

    request_id = repo.create_or_get(new_request())

    assert request_id == 41
    assert engine.begin_count == 1
    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_report_generation_request" in sql
    assert "INSERT IGNORE" not in sql
    assert ":idempotency_key" in sql
    assert params["data_cutoff_time"] == datetime(2026, 7, 10, 15, 30)
    assert params["data_cutoff_time"].tzinfo is None


def test_create_or_get_returns_existing_id_after_matching_unique_race() -> None:
    engine = Engine(
        [
            mysql_integrity_error(
                1062,
                "Duplicate entry for key 'uk_report_request_idempotency'",
            ),
            Result(rows=[matching_row()]),
        ]
    )
    repo = MysqlReportRequestRepo(engine)

    request_id = repo.create_or_get(new_request())

    assert request_id == 41
    assert engine.begin_count == 2
    select_sql, select_params = engine.connection.executions[1]
    assert "WHERE idempotency_key = :idempotency_key" in select_sql
    assert "FOR UPDATE" in select_sql
    assert select_params == {"idempotency_key": "manual-form-1"}


def test_create_or_get_rejects_same_key_with_different_immutable_payload() -> None:
    engine = Engine(
        [
            mysql_integrity_error(
                1062,
                "Duplicate entry for key 'uk_report_request_idempotency'",
            ),
            Result(rows=[matching_row(source_name="另一群")]),
        ]
    )

    with pytest.raises(ReportRequestConflictError) as captured:
        MysqlReportRequestRepo(engine).create_or_get(new_request())

    assert "manual-form-1" not in str(captured.value)
    assert "核心群A" not in str(captured.value)


def test_create_or_get_does_not_swallow_other_database_errors() -> None:
    error = mysql_integrity_error(1452, "foreign key failure")
    engine = Engine([error])

    with pytest.raises(IntegrityError) as captured:
        MysqlReportRequestRepo(engine).create_or_get(new_request())

    assert captured.value is error
    assert len(engine.connection.executions) == 1


def test_claim_next_commits_recovery_before_atomic_lock_and_claim_transaction() -> None:
    engine = Engine(
        [
            Result(rowcount=1),
            Result(rows=[request_row()]),
            Result(rowcount=1),
        ]
    )
    repo = MysqlReportRequestRepo(engine)

    claimed = repo.claim_next(NOW, "pipeline-1", 120)

    assert claimed is not None
    assert claimed.id == 41
    assert claimed.status is ReportRequestStatus.RUNNING
    assert claimed.worker_id == "pipeline-1"
    assert claimed.start_time == NOW
    assert claimed.lease_expires_at == datetime(2026, 7, 10, 15, 32, tzinfo=ZONE)
    assert claimed.data_cutoff_time == NOW
    assert engine.begin_count == 2
    recover_sql, recover_params = engine.connection.executions[0]
    assert "status = 'running'" in recover_sql
    assert "lease_expires_at <= :now" in recover_sql
    assert recover_params == {"now": datetime(2026, 7, 10, 15, 30)}
    select_sql, select_params = engine.connection.executions[1]
    assert "status = 'pending'" in select_sql
    assert "ORDER BY create_time ASC, id ASC" in select_sql
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert select_params == {}
    update_sql, update_params = engine.connection.executions[2]
    assert "status = 'running'" in update_sql
    assert "status = 'pending'" in update_sql
    assert update_params["lease_expires_at"] == datetime(2026, 7, 10, 15, 32)


def test_claim_next_returns_none_when_no_pending_request() -> None:
    engine = Engine([Result(rowcount=0), Result(rows=[])])

    assert MysqlReportRequestRepo(engine).claim_next(NOW, "pipeline-1", 120) is None
    assert len(engine.connection.executions) == 2


def test_claim_next_rejects_lost_state_transition() -> None:
    engine = Engine(
        [
            Result(rowcount=0),
            Result(rows=[request_row()]),
            Result(rowcount=0),
        ]
    )

    with pytest.raises(ReportRequestStateError, match="pending"):
        MysqlReportRequestRepo(engine).claim_next(NOW, "pipeline-1", 120)


def test_recover_expired_only_resets_expired_running_requests() -> None:
    engine = Engine([Result(rowcount=2)])

    recovered = MysqlReportRequestRepo(engine).recover_expired(NOW)

    assert recovered == 2
    sql, params = engine.connection.executions[0]
    assert "SET status = 'pending'" in sql
    assert "worker_id = NULL" in sql
    assert "lease_expires_at = NULL" in sql
    assert "start_time = NULL" in sql
    assert "status = 'running'" in sql
    assert "lease_expires_at <= :now" in sql
    assert "success" not in sql.lower()
    assert params == {"now": datetime(2026, 7, 10, 15, 30)}


@pytest.mark.parametrize(
    ("method_name", "expected_status"),
    [
        ("mark_success", "success"),
        ("mark_partial_success", "partial_success"),
        ("mark_failed", "failed"),
    ],
)
def test_terminal_transitions_only_finish_running_request(
    method_name: str,
    expected_status: str,
) -> None:
    engine = Engine([Result(rowcount=1)])
    repo = MysqlReportRequestRepo(engine)

    if method_name == "mark_success":
        getattr(repo, method_name)(41, NOW)
    else:
        getattr(repo, method_name)(41, "safe failure", NOW)

    sql, params = engine.connection.executions[0]
    assert f"status = '{expected_status}'" in sql
    assert "WHERE id = :request_id" in sql
    assert "status = 'running'" in sql
    assert "lease_expires_at = NULL" in sql
    assert params["request_id"] == 41
    assert params["now"] == datetime(2026, 7, 10, 15, 30)


@pytest.mark.parametrize(
    ("method_name", "expected_status"),
    [
        ("mark_success_owned", "success"),
        ("mark_partial_success_owned", "partial_success"),
        ("mark_failed_owned", "failed"),
    ],
)
def test_owned_terminal_transitions_compare_and_set_claim_identity(
    method_name: str,
    expected_status: str,
) -> None:
    engine = Engine([Result(rowcount=1)])
    repo = MysqlReportRequestRepo(engine)
    request = running_request()

    if method_name == "mark_success_owned":
        getattr(repo, method_name)(request, NOW)
    else:
        getattr(repo, method_name)(request, "safe failure", NOW)

    sql, params = engine.connection.executions[0]
    assert f"status = '{expected_status}'" in sql
    assert "worker_id = :worker_id" in sql
    assert "start_time = :start_time" in sql
    assert "lease_expires_at = :expected_lease_expires_at" in sql
    assert "lease_expires_at > :now" in sql
    assert params["request_id"] == 41
    assert params["worker_id"] == "pipeline-1"
    assert params["start_time"] == datetime(2026, 7, 10, 15, 30)
    assert params["expected_lease_expires_at"] == datetime(2026, 7, 10, 15, 32)


def test_terminal_error_summary_is_desensitized_and_capped_at_500() -> None:
    engine = Engine([Result(rowcount=1)])
    unsafe = (
        "<script>bad()</script> https://secret.example/path "
        "手机号13800138000 微信wx_secret "
        + "x" * 600
    )

    MysqlReportRequestRepo(engine).mark_failed(
        41,
        unsafe,
        NOW,
    )

    _, params = engine.connection.executions[0]
    summary = params["error_summary"]
    assert len(summary) <= 500
    assert "script" not in summary
    assert "secret.example" not in summary
    assert "13800138000" not in summary
    assert "wx_secret" not in summary


def test_terminal_transition_rejects_request_that_is_not_running() -> None:
    engine = Engine([Result(rowcount=0)])

    with pytest.raises(ReportRequestStateError, match="running"):
        MysqlReportRequestRepo(engine).mark_success(
            41,
            NOW,
        )


def test_owned_terminal_rejects_stale_claim_identity() -> None:
    engine = Engine([Result(rowcount=0)])

    with pytest.raises(ReportRequestStateError, match="owned"):
        MysqlReportRequestRepo(engine).mark_success_owned(running_request(), NOW)


def test_report_request_rejects_invalid_runtime_report_type() -> None:
    with pytest.raises(ValueError, match="report_type"):
        ReportRequest(
            **{
                **request_row(
                    status=ReportRequestStatus.RUNNING,
                    worker_id="pipeline-1",
                    lease_expires_at=NOW + timedelta(minutes=2),
                    start_time=NOW,
                ),
                "report_type": "bogus",
                "data_cutoff_time": NOW,
                "create_time": NOW,
            }
        )


def test_get_request_returns_complete_timezone_aware_record() -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    request_row(
                        status="running",
                        worker_id="pipeline-1",
                        lease_expires_at=datetime(2026, 7, 10, 15, 32),
                        start_time=datetime(2026, 7, 10, 15, 30),
                    )
                ]
            )
        ]
    )

    request = MysqlReportRequestRepo(engine).get_request(41)

    assert request is not None
    assert request.idempotency_key == "manual-form-1"
    assert request.status is ReportRequestStatus.RUNNING
    assert request.worker_id == "pipeline-1"
    assert request.create_time == NOW
    assert request.lease_expires_at == datetime(2026, 7, 10, 15, 32, tzinfo=ZONE)
    assert request.error_summary is None


def test_get_request_never_exposes_unsafe_persisted_error_summary() -> None:
    unsafe = "https://secret.example/path 13800138000 wx_secret " + "x" * 600
    engine = Engine(
        [
            Result(
                rows=[
                    request_row(
                        status="failed",
                        worker_id="pipeline-1",
                        error_summary=unsafe,
                        start_time=datetime(2026, 7, 10, 15, 30),
                        end_time=datetime(2026, 7, 10, 15, 31),
                    )
                ]
            )
        ]
    )

    request = MysqlReportRequestRepo(engine).get_request(41)

    assert request is not None
    assert request.error_summary is not None
    assert len(request.error_summary) <= 500
    assert "secret.example" not in request.error_summary
    assert "13800138000" not in request.error_summary
    assert "wx_secret" not in request.error_summary
