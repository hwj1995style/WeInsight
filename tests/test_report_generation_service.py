from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.domain.report_lifecycle import GenerationTrigger, ReportStatus
from app.services.report_generation_service import (
    ReportGenerationService,
    ReportValidationError,
)
from app.storage.report_request_repo import (
    NewReportRequest,
    ReportRequest,
    ReportRequestConflictError,
    ReportRequestStatus,
    ReportType,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 15, 30, tzinfo=ZONE)
EXECUTION_NOW = datetime(2026, 7, 10, 16, 0, tzinfo=ZONE)


class FakeRequestRepo:
    def __init__(self) -> None:
        self.requests: dict[int, NewReportRequest] = {}
        self.ids_by_key: dict[str, int] = {}
        self.terminal_calls: list[tuple[str, int, str | None, datetime]] = []
        self.terminal_identities: list[tuple[str | None, datetime | None, datetime | None]] = []

    def create_or_get(self, request: NewReportRequest) -> int:
        existing_id = self.ids_by_key.get(request.idempotency_key)
        if existing_id is not None:
            if self.requests[existing_id] != request:
                raise ReportRequestConflictError("idempotency payload conflict")
            return existing_id
        request_id = len(self.requests) + 1
        self.requests[request_id] = request
        self.ids_by_key[request.idempotency_key] = request_id
        return request_id

    def mark_success(self, request_id: int, now: datetime) -> None:
        self.terminal_calls.append(("success", request_id, None, now))

    def mark_partial_success(
        self,
        request_id: int,
        error_summary: str,
        now: datetime,
    ) -> None:
        self.terminal_calls.append(
            ("partial_success", request_id, error_summary, now)
        )

    def mark_failed(
        self,
        request_id: int,
        error_summary: str,
        now: datetime,
    ) -> None:
        self.terminal_calls.append(("failed", request_id, error_summary, now))

    def mark_success_owned(self, request: ReportRequest, now: datetime) -> None:
        self.terminal_calls.append(("success", request.id, None, now))
        self.terminal_identities.append(
            (request.worker_id, request.start_time, request.lease_expires_at)
        )

    def mark_partial_success_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        self.terminal_calls.append(
            ("partial_success", request.id, error_summary, now)
        )
        self.terminal_identities.append(
            (request.worker_id, request.start_time, request.lease_expires_at)
        )

    def mark_failed_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        self.terminal_calls.append(("failed", request.id, error_summary, now))
        self.terminal_identities.append(
            (request.worker_id, request.start_time, request.lease_expires_at)
        )


class FakeStatsRepo:
    def __init__(self, field: str, names: list[str]) -> None:
        self.field = field
        self.names = names
        self.calls: list[tuple[date, str | None]] = []
        self.error: Exception | None = None

    def list_daily_report_stats(self, report_date: date, source_name: str | None):
        self.calls.append((report_date, source_name))
        if self.error is not None:
            raise self.error
        names = self.names if source_name is None else [source_name]
        return [SimpleNamespace(**{self.field: name}) for name in names]


class FakeGroupReportService:
    def __init__(self, names: list[str], log: list[str]) -> None:
        self.repo = FakeStatsRepo("group_name", names)
        self.log = log
        self.calls = []
        self.fail_names: set[str] = set()

    def generate_once(
        self,
        *,
        report_date,
        group_name,
        generate_time,
        lifecycle,
    ):
        assert group_name is not None
        self.log.append(f"group:{group_name}")
        self.calls.append((report_date, group_name, generate_time, lifecycle))
        if group_name in self.fail_names:
            raise RuntimeError(f"group failed {group_name}")
        return SimpleNamespace(generated_count=1)


class FakeArticleReportService:
    def __init__(self, names: list[str], log: list[str]) -> None:
        self.repo = FakeStatsRepo("account_name", names)
        self.log = log
        self.calls = []
        self.fail_names: set[str] = set()

    def generate_once(
        self,
        *,
        report_date,
        account_name,
        generate_time,
        lifecycle,
    ):
        assert account_name is not None
        self.log.append(f"article:{account_name}")
        self.calls.append((report_date, account_name, generate_time, lifecycle))
        if account_name in self.fail_names:
            raise RuntimeError(f"article failed {account_name}")
        return SimpleNamespace(generated_count=1)


class FakeSummaryReportService:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls = []
        self.error: Exception | None = None

    def generate(self, report_date, generate_time):
        self.log.append("summary")
        self.calls.append((report_date, generate_time))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(markdown_body="# summary")


def build_service(
    *,
    group_names: list[str] | None = None,
    article_names: list[str] | None = None,
):
    log: list[str] = []
    repo = FakeRequestRepo()
    group = FakeGroupReportService(group_names or [], log)
    article = FakeArticleReportService(article_names or [], log)
    summary = FakeSummaryReportService(log)
    service = ReportGenerationService(
        repo=repo,
        group_report_service=group,
        article_report_service=article,
        summary_report_service=summary,
    )
    return service, repo, group, article, summary, log


def claimed_request(**changes) -> ReportRequest:
    values = {
        "id": 41,
        "idempotency_key": "manual-form-1",
        "report_type": ReportType.ALL,
        "report_date": date(2026, 7, 10),
        "source_name": None,
        "generation_trigger": GenerationTrigger.MANUAL,
        "data_cutoff_time": NOW,
        "requested_by": "admin",
        "status": ReportRequestStatus.RUNNING,
        "worker_id": "pipeline-1",
        "lease_expires_at": EXECUTION_NOW + timedelta(minutes=2),
        "error_summary": None,
        "create_time": NOW,
        "start_time": EXECUTION_NOW,
        "end_time": None,
    }
    values.update(changes)
    return ReportRequest(**values)


def test_manual_today_request_uses_request_time_cutoff() -> None:
    service, repo, *_ = build_service()

    request_id = service.request_manual(
        ReportType.ALL,
        date(2026, 7, 10),
        None,
        " admin ",
        " manual-form-1 ",
        NOW,
    )

    saved = repo.requests[request_id]
    assert saved.data_cutoff_time == NOW
    assert saved.generation_trigger is GenerationTrigger.MANUAL
    assert saved.requested_by == "admin"


def test_manual_history_request_remains_manual_with_current_cutoff() -> None:
    service, repo, *_ = build_service()

    request_id = service.request_manual(
        ReportType.GROUP,
        date(2026, 7, 9),
        "核心群A",
        "admin",
        "manual-history-1",
        NOW,
    )

    saved = repo.requests[request_id]
    assert saved.report_date == date(2026, 7, 9)
    assert saved.data_cutoff_time == NOW
    assert saved.generation_trigger is GenerationTrigger.MANUAL


def test_manual_future_request_is_rejected_before_repo_write() -> None:
    service, repo, *_ = build_service()

    with pytest.raises(ReportValidationError, match="future"):
        service.request_manual(
            ReportType.ALL,
            date(2026, 7, 11),
            None,
            "admin",
            "manual-future-1",
            NOW,
        )

    assert repo.requests == {}


@pytest.mark.parametrize(
    ("report_type", "source_name", "actor", "idempotency_key"),
    [
        (ReportType.SUMMARY, "核心群A", "admin", "key-1"),
        (ReportType.ALL, "核心群A", "admin", "key-2"),
        (ReportType.GROUP, "   ", "admin", "key-3"),
        (ReportType.ARTICLE, None, "admin\nroot", "key-4"),
        (ReportType.ARTICLE, None, "admin", "k" * 101),
    ],
)
def test_manual_request_rejects_invalid_source_actor_or_key(
    report_type,
    source_name,
    actor,
    idempotency_key,
) -> None:
    service, repo, *_ = build_service()

    with pytest.raises(ReportValidationError):
        service.request_manual(
            report_type,
            date(2026, 7, 10),
            source_name,
            actor,
            idempotency_key,
            NOW,
        )

    assert repo.requests == {}


def test_same_manual_idempotency_key_same_payload_returns_existing_request() -> None:
    service, *_ = build_service()

    first = service.request_manual(
        ReportType.GROUP,
        date(2026, 7, 10),
        "核心群A",
        "admin",
        "same-key",
        NOW,
    )
    second = service.request_manual(
        ReportType.GROUP,
        date(2026, 7, 10),
        "核心群A",
        "admin",
        "same-key",
        NOW,
    )

    assert second == first


def test_same_manual_idempotency_key_different_payload_conflicts() -> None:
    service, *_ = build_service()
    service.request_manual(
        ReportType.GROUP,
        date(2026, 7, 10),
        "核心群A",
        "admin",
        "same-key",
        NOW,
    )

    with pytest.raises(ReportRequestConflictError):
        service.request_manual(
            ReportType.GROUP,
            date(2026, 7, 10),
            "另一群",
            "admin",
            "same-key",
            NOW,
        )


def test_compensation_request_is_deterministic_final_input_for_previous_date() -> None:
    service, repo, *_ = build_service()

    first = service.ensure_compensation_request(date(2026, 7, 9), NOW)
    second = service.ensure_compensation_request(
        date(2026, 7, 9),
        NOW + timedelta(minutes=5),
    )

    assert second == first
    saved = repo.requests[first]
    assert saved.idempotency_key == "compensation:all:2026-07-09"
    assert saved.report_type is ReportType.ALL
    assert saved.generation_trigger is GenerationTrigger.COMPENSATION
    assert saved.data_cutoff_time == datetime(2026, 7, 10, 0, 10, tzinfo=ZONE)
    assert saved.requested_by == "system"


@pytest.mark.parametrize("report_date", [date(2026, 7, 10), date(2026, 7, 11)])
def test_compensation_rejects_today_and_future(report_date: date) -> None:
    service, repo, *_ = build_service()

    with pytest.raises(ReportValidationError, match="previous"):
        service.ensure_compensation_request(report_date, NOW)

    assert repo.requests == {}


def test_execute_all_runs_group_then_article_then_summary_per_source() -> None:
    service, repo, group, article, summary, log = build_service(
        group_names=["群B", "群A", "群A"],
        article_names=["号B", "号A"],
    )

    result = service.execute_request(claimed_request(), "pipeline-1", EXECUTION_NOW)

    assert result.status == "success"
    assert result.success_count == 5
    assert result.failed_count == 0
    assert result.error_summary is None
    assert log == ["group:群A", "group:群B", "article:号A", "article:号B", "summary"]
    assert repo.terminal_calls == [("success", 41, None, EXECUTION_NOW)]
    assert repo.terminal_identities == [
        ("pipeline-1", EXECUTION_NOW, EXECUTION_NOW + timedelta(minutes=2))
    ]
    for call in group.calls + article.calls:
        generate_time = call[2]
        lifecycle = call[3]
        assert generate_time == datetime(2026, 7, 10, 16, 0)
        assert lifecycle.report_status is ReportStatus.PROVISIONAL
        assert lifecycle.data_cutoff_time == NOW
        assert lifecycle.generation_trigger is GenerationTrigger.MANUAL
        assert lifecycle.last_generated_by == "admin"
    assert summary.calls == [(date(2026, 7, 10), datetime(2026, 7, 10, 16, 0))]


def test_execute_specified_source_does_not_use_bulk_stats_enumeration() -> None:
    service, repo, group, *_ = build_service(group_names=["其他群"])
    request = claimed_request(
        report_type=ReportType.GROUP,
        source_name="指定群",
    )

    result = service.execute_request(request, "pipeline-1", EXECUTION_NOW)

    assert result.status == "success"
    assert [call[1] for call in group.calls] == ["指定群"]
    assert group.repo.calls == []
    assert repo.terminal_calls[0][0] == "success"


def test_execute_compensation_is_final_and_preserves_scheduled_cutoff() -> None:
    service, repo, group, *_ = build_service()
    cutoff = datetime(2026, 7, 10, 0, 10, tzinfo=ZONE)
    request = claimed_request(
        report_type=ReportType.GROUP,
        report_date=date(2026, 7, 9),
        source_name="核心群A",
        generation_trigger=GenerationTrigger.COMPENSATION,
        data_cutoff_time=cutoff,
        requested_by="system",
        idempotency_key="compensation:all:2026-07-09",
    )

    result = service.execute_request(request, "pipeline-1", EXECUTION_NOW)

    assert result.status == "success"
    lifecycle = group.calls[0][3]
    assert lifecycle.report_status is ReportStatus.FINAL
    assert lifecycle.generation_trigger is GenerationTrigger.COMPENSATION
    assert lifecycle.data_cutoff_time == cutoff
    assert lifecycle.last_generated_by == "system"
    assert repo.terminal_calls[0][0] == "success"


def test_one_source_failure_yields_partial_success_and_continues() -> None:
    service, repo, group, *_ = build_service(group_names=["群A", "群B", "群C"])
    group.fail_names = {"群B"}
    request = claimed_request(report_type=ReportType.GROUP)

    result = service.execute_request(request, "pipeline-1", EXECUTION_NOW)

    assert result.status == "partial_success"
    assert result.success_count == 2
    assert result.failed_count == 1
    assert [call[1] for call in group.calls] == ["群A", "群B", "群C"]
    assert repo.terminal_calls[0][0] == "partial_success"


def test_all_sources_failed_marks_request_failed() -> None:
    service, repo, group, *_ = build_service(group_names=["群A", "群B"])
    group.fail_names = {"群A", "群B"}
    request = claimed_request(report_type=ReportType.GROUP)

    result = service.execute_request(request, "pipeline-1", EXECUTION_NOW)

    assert result.status == "failed"
    assert result.success_count == 0
    assert result.failed_count == 2
    assert repo.terminal_calls[0][0] == "failed"


def test_group_enumeration_failure_does_not_skip_article_or_summary() -> None:
    service, repo, group, article, _, log = build_service(article_names=["号A"])
    group.repo.error = RuntimeError("group stats unavailable")

    result = service.execute_request(claimed_request(), "pipeline-1", EXECUTION_NOW)

    assert result.status == "partial_success"
    assert result.success_count == 2
    assert result.failed_count == 1
    assert log == ["article:号A", "summary"]
    assert article.calls
    assert repo.terminal_calls[0][0] == "partial_success"


def test_error_summary_is_safe_and_capped() -> None:
    service, repo, group, *_ = build_service(group_names=["群A"])
    group.fail_names = {"群A"}

    def unsafe_generate(**kwargs):
        raise RuntimeError(
            "https://secret.example/path 13800138000 wx_secret " + "x" * 800
        )

    group.generate_once = unsafe_generate
    request = claimed_request(report_type=ReportType.GROUP)

    result = service.execute_request(request, "pipeline-1", EXECUTION_NOW)

    assert result.error_summary is not None
    assert len(result.error_summary) <= 500
    assert "secret.example" not in result.error_summary
    assert "13800138000" not in result.error_summary
    assert "wx_secret" not in result.error_summary
    assert repo.terminal_calls[0][2] == result.error_summary


def test_invalid_request_lifecycle_is_marked_failed_instead_of_left_running() -> None:
    service, repo, *_ = build_service()
    invalid = claimed_request(report_date=date(2026, 7, 11))

    result = service.execute_request(invalid, "pipeline-1", EXECUTION_NOW)

    assert result.status == "failed"
    assert result.success_count == 0
    assert result.failed_count == 1
    assert repo.terminal_calls[0][0] == "failed"


def test_execute_rejects_wrong_worker_without_mutating_request() -> None:
    service, repo, *_ = build_service()

    with pytest.raises(ReportValidationError, match="worker"):
        service.execute_request(claimed_request(), "other-worker", EXECUTION_NOW)

    assert repo.terminal_calls == []


def test_execute_rejects_expired_lease_without_running_targets() -> None:
    service, repo, group, *_ = build_service(group_names=["群A"])
    expired = claimed_request(lease_expires_at=EXECUTION_NOW)

    with pytest.raises(ReportValidationError, match="lease"):
        service.execute_request(expired, "pipeline-1", EXECUTION_NOW)

    assert group.calls == []
    assert repo.terminal_calls == []


def test_execute_revalidates_mutated_report_type_and_never_marks_success() -> None:
    service, repo, *_ = build_service()
    malformed = claimed_request()
    object.__setattr__(malformed, "report_type", "bogus")

    with pytest.raises(ReportValidationError, match="report_type"):
        service.execute_request(malformed, "pipeline-1", EXECUTION_NOW)

    assert repo.terminal_calls == []
