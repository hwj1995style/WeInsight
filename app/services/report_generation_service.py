from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.report_lifecycle import GenerationTrigger, ReportLifecycle
from app.storage.collection_event_repo import sanitize_output
from app.storage.report_request_repo import (
    NewReportRequest,
    ReportRequest,
    ReportRequestStatus,
    ReportType,
)


_ZONE = ZoneInfo("Asia/Shanghai")


class ReportValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportExecutionResult:
    status: str
    success_count: int
    failed_count: int
    error_summary: str | None


class ReportRequestRepo(Protocol):
    def create_or_get(self, request: NewReportRequest) -> int:
        ...

    def mark_success_owned(
        self,
        request: ReportRequest,
        now: datetime,
    ) -> None:
        ...

    def mark_partial_success_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        ...

    def mark_failed_owned(
        self,
        request: ReportRequest,
        error_summary: str,
        now: datetime,
    ) -> None:
        ...


class ReportStatsRepo(Protocol):
    def list_daily_report_stats(self, report_date: date, source_name: str | None):
        ...


class GroupReportService(Protocol):
    repo: ReportStatsRepo

    def generate_once(
        self,
        *,
        report_date: date,
        group_name: str | None,
        generate_time: datetime,
        lifecycle: ReportLifecycle,
    ):
        ...


class ArticleReportService(Protocol):
    repo: ReportStatsRepo

    def generate_once(
        self,
        *,
        report_date: date,
        account_name: str | None,
        generate_time: datetime,
        lifecycle: ReportLifecycle,
    ):
        ...


class SummaryReportService(Protocol):
    def generate(self, report_date: date, generate_time: datetime):
        ...


class ReportGenerationService:
    def __init__(
        self,
        *,
        repo: ReportRequestRepo,
        group_report_service: GroupReportService,
        article_report_service: ArticleReportService,
        summary_report_service: SummaryReportService,
    ) -> None:
        self.repo = repo
        self.group_report_service = group_report_service
        self.article_report_service = article_report_service
        self.summary_report_service = summary_report_service

    def request_manual(
        self,
        report_type: ReportType,
        report_date: date,
        source_name: str | None,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> int:
        try:
            _require_shanghai_datetime(now, "now")
            lifecycle = ReportLifecycle.manual_for_date(report_date, now, actor)
            request = NewReportRequest(
                idempotency_key=idempotency_key,
                report_type=report_type,
                report_date=report_date,
                source_name=source_name,
                generation_trigger=GenerationTrigger.MANUAL,
                data_cutoff_time=lifecycle.data_cutoff_time,
                requested_by=lifecycle.last_generated_by,
            )
        except ValueError as exc:
            raise ReportValidationError(str(exc)) from None
        return self.repo.create_or_get(request)

    def ensure_compensation_request(
        self,
        report_date: date,
        now: datetime,
    ) -> int:
        try:
            _require_shanghai_datetime(now, "now")
            if not isinstance(report_date, date) or isinstance(report_date, datetime):
                raise ValueError("report_date must be a calendar date")
            if report_date >= now.date():
                raise ValueError("compensation report_date must be a previous date")
            scheduled_cutoff = datetime.combine(
                report_date + timedelta(days=1),
                time(0, 10),
                tzinfo=_ZONE,
            )
            request = NewReportRequest(
                idempotency_key=f"compensation:all:{report_date.isoformat()}",
                report_type=ReportType.ALL,
                report_date=report_date,
                source_name=None,
                generation_trigger=GenerationTrigger.COMPENSATION,
                data_cutoff_time=scheduled_cutoff,
                requested_by="system",
            )
        except ValueError as exc:
            raise ReportValidationError(str(exc)) from None
        return self.repo.create_or_get(request)

    def execute_request(
        self,
        request: ReportRequest,
        worker_id: str,
        now: datetime,
    ) -> ReportExecutionResult:
        if not isinstance(request, ReportRequest):
            raise ReportValidationError("request must be a ReportRequest")
        try:
            request.validate()
        except ValueError as exc:
            raise ReportValidationError(str(exc)) from None
        normalized_worker_id = _required_text(worker_id, "worker_id", 100)
        _require_shanghai_datetime(now, "now")
        if (
            request.status is not ReportRequestStatus.RUNNING
            or request.worker_id != normalized_worker_id
        ):
            raise ReportValidationError("request is not owned by this worker")
        if request.lease_expires_at is None or request.lease_expires_at <= now:
            raise ReportValidationError("request lease has expired")

        try:
            lifecycle = _lifecycle_for_request(request)
            success_count, failed_count, errors = self._execute_targets(
                request,
                lifecycle,
                _to_db_datetime(now),
            )
        except Exception as exc:
            error_summary = _aggregate_errors([_safe_exception("request", exc)])
            self.repo.mark_failed_owned(request, error_summary, now)
            return ReportExecutionResult(
                status=ReportRequestStatus.FAILED.value,
                success_count=0,
                failed_count=1,
                error_summary=error_summary,
            )

        if failed_count == 0:
            self.repo.mark_success_owned(request, now)
            return ReportExecutionResult(
                status=ReportRequestStatus.SUCCESS.value,
                success_count=success_count,
                failed_count=0,
                error_summary=None,
            )

        error_summary = _aggregate_errors(errors)
        if success_count:
            self.repo.mark_partial_success_owned(request, error_summary, now)
            status = ReportRequestStatus.PARTIAL_SUCCESS
        else:
            self.repo.mark_failed_owned(request, error_summary, now)
            status = ReportRequestStatus.FAILED
        return ReportExecutionResult(
            status=status.value,
            success_count=success_count,
            failed_count=failed_count,
            error_summary=error_summary,
        )

    def _execute_targets(
        self,
        request: ReportRequest,
        lifecycle: ReportLifecycle,
        generate_time: datetime,
    ) -> tuple[int, int, list[str]]:
        success_count = 0
        failed_count = 0
        errors: list[str] = []

        if request.report_type in {ReportType.GROUP, ReportType.ALL}:
            try:
                group_names = self._group_names(request)
            except Exception as exc:
                failed_count += 1
                errors.append(_safe_exception("group enumeration", exc))
            else:
                for group_name in group_names:
                    try:
                        self.group_report_service.generate_once(
                            report_date=request.report_date,
                            group_name=group_name,
                            generate_time=generate_time,
                            lifecycle=lifecycle,
                        )
                        success_count += 1
                    except Exception as exc:
                        failed_count += 1
                        errors.append(_safe_exception("group target", exc))

        if request.report_type in {ReportType.ARTICLE, ReportType.ALL}:
            try:
                account_names = self._article_names(request)
            except Exception as exc:
                failed_count += 1
                errors.append(_safe_exception("article enumeration", exc))
            else:
                for account_name in account_names:
                    try:
                        self.article_report_service.generate_once(
                            report_date=request.report_date,
                            account_name=account_name,
                            generate_time=generate_time,
                            lifecycle=lifecycle,
                        )
                        success_count += 1
                    except Exception as exc:
                        failed_count += 1
                        errors.append(_safe_exception("article target", exc))

        if request.report_type in {ReportType.SUMMARY, ReportType.ALL}:
            try:
                self.summary_report_service.generate(
                    request.report_date,
                    generate_time,
                )
                success_count += 1
            except Exception as exc:
                failed_count += 1
                errors.append(_safe_exception("summary", exc))

        return success_count, failed_count, errors

    def _group_names(self, request: ReportRequest) -> list[str]:
        if request.source_name is not None:
            return [request.source_name]
        rows = self.group_report_service.repo.list_daily_report_stats(
            request.report_date,
            None,
        )
        return _source_names(rows, "group_name")

    def _article_names(self, request: ReportRequest) -> list[str]:
        if request.source_name is not None:
            return [request.source_name]
        rows = self.article_report_service.repo.list_daily_report_stats(
            request.report_date,
            None,
        )
        return _source_names(rows, "account_name")


def _lifecycle_for_request(request: ReportRequest) -> ReportLifecycle:
    if request.generation_trigger is GenerationTrigger.MANUAL:
        return ReportLifecycle.manual_for_date(
            request.report_date,
            request.data_cutoff_time,
            request.requested_by,
        )
    if request.generation_trigger in {
        GenerationTrigger.AUTOMATIC,
        GenerationTrigger.COMPENSATION,
    }:
        return ReportLifecycle.final(
            request.data_cutoff_time,
            request.generation_trigger,
            request.requested_by,
        )
    raise ReportValidationError("request generation_trigger is not executable")


def _source_names(rows, field: str) -> list[str]:
    names = {
        _required_text(getattr(row, field, None), field, 200)
        for row in rows
    }
    return sorted(names)


def _required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReportValidationError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ReportValidationError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ReportValidationError(f"{field} must be at most {maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ReportValidationError(f"{field} must not contain control characters")
    return normalized


def _require_shanghai_datetime(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != "Asia/Shanghai"
    ):
        raise ReportValidationError(f"{field} must use Asia/Shanghai ZoneInfo")
    return value


def _to_db_datetime(value: datetime) -> datetime:
    return _require_shanghai_datetime(value, "now").replace(tzinfo=None)


def _safe_exception(stage: str, error: Exception) -> str:
    return sanitize_output(f"{stage} failed: {error}", maximum=500).strip()


def _aggregate_errors(errors: list[str]) -> str:
    safe = sanitize_output("; ".join(errors), maximum=500).strip()
    return safe or "report generation failed"
