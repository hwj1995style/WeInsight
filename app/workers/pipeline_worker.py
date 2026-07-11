from __future__ import annotations

import hashlib
import json
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.storage.collection_event_repo import (
    NewCollectionEvent,
    sanitize_output,
)
from app.storage.worker_heartbeat_repo import WorkerHeartbeatRecord


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


@dataclass(frozen=True, slots=True)
class PipelineTickResult:
    group_clean_success: int
    group_analysis_success: int
    article_parse_success: int
    article_analysis_success: int
    report_request_status: str | None


class GroupCleanService(Protocol):
    def clean_once(self, limit: int, clean_time: datetime): ...


class GroupAnalysisService(Protocol):
    def analyze_once(self, limit: int, analyze_time: datetime): ...


class ArticleParseService(Protocol):
    def parse_once(self, limit: int, parse_time: datetime): ...


class ArticleAnalysisService(Protocol):
    def analyze_once(self, limit: int, analyze_time: datetime): ...


class ReportRepo(Protocol):
    def claim_next(
        self,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
    ): ...


class ReportService(Protocol):
    def execute_request(self, request, worker_id: str, now: datetime): ...

    def ensure_compensation_request(
        self,
        report_date,
        now: datetime,
    ) -> int: ...


class EventRepo(Protocol):
    def append_event(self, event: NewCollectionEvent) -> int: ...


class HeartbeatRepo(Protocol):
    def upsert_heartbeat(self, record: WorkerHeartbeatRecord) -> None: ...


class PipelineWorker:
    def __init__(
        self,
        *,
        group_clean_service: GroupCleanService,
        group_analysis_service: GroupAnalysisService,
        article_parse_service: ArticleParseService,
        article_analysis_service: ArticleAnalysisService,
        report_repo: ReportRepo,
        report_service: ReportService,
        event_repo: EventRepo,
        heartbeat_repo: HeartbeatRepo,
        worker_id: str,
        hostname: str,
        process_id: int,
        version: str,
        start_time: datetime,
        report_lease_seconds: int,
        group_clean_batch_size: int,
        group_analysis_batch_size: int,
        article_parse_batch_size: int,
        article_analysis_batch_size: int,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        _required_text(worker_id, "worker_id", 100)
        _required_text(hostname, "hostname", 255)
        _positive_integer(process_id, "process_id")
        _required_text(version, "version", 100)
        _require_now(start_time)
        for field, value in (
            ("report_lease_seconds", report_lease_seconds),
            ("group_clean_batch_size", group_clean_batch_size),
            ("group_analysis_batch_size", group_analysis_batch_size),
            ("article_parse_batch_size", article_parse_batch_size),
            ("article_analysis_batch_size", article_analysis_batch_size),
        ):
            _positive_integer(value, field)
        self.group_clean_service = group_clean_service
        self.group_analysis_service = group_analysis_service
        self.article_parse_service = article_parse_service
        self.article_analysis_service = article_analysis_service
        self.report_repo = report_repo
        self.report_service = report_service
        self.event_repo = event_repo
        self.heartbeat_repo = heartbeat_repo
        self.worker_id = worker_id
        self.hostname = hostname
        self.process_id = process_id
        self.version = version
        self.start_time = start_time
        self.report_lease_seconds = report_lease_seconds
        self.group_clean_batch_size = group_clean_batch_size
        self.group_analysis_batch_size = group_analysis_batch_size
        self.article_parse_batch_size = article_parse_batch_size
        self.article_analysis_batch_size = article_analysis_batch_size
        self.now_provider = now_provider or _shanghai_now

    def run_tick(self, now: datetime) -> PipelineTickResult:
        _require_now(now)
        group_clean_success = self._run_stage(
            "group_clean",
            lambda: self.group_clean_service.clean_once(
                self.group_clean_batch_size,
                now,
            ),
        )
        group_analysis_success = self._run_stage(
            "group_analysis",
            lambda: self.group_analysis_service.analyze_once(
                self.group_analysis_batch_size,
                now,
            ),
        )
        article_parse_success = self._run_stage(
            "article_parse",
            lambda: self.article_parse_service.parse_once(
                self.article_parse_batch_size,
                now,
            ),
        )
        article_analysis_success = self._run_stage(
            "article_analysis",
            lambda: self.article_analysis_service.analyze_once(
                self.article_analysis_batch_size,
                now,
            ),
        )
        report_request_status = self._run_report(now)
        return PipelineTickResult(
            group_clean_success=group_clean_success,
            group_analysis_success=group_analysis_success,
            article_parse_success=article_parse_success,
            article_analysis_success=article_analysis_success,
            report_request_status=report_request_status,
        )

    def ensure_daily_compensation(self, now: datetime) -> int:
        _require_now(now)
        return int(
            self.report_service.ensure_compensation_request(
                now.date() - timedelta(days=1),
                now,
            )
        )

    def heartbeat(self, now: datetime) -> None:
        self._write_heartbeat(now, "running")

    def run_tick_now(self) -> PipelineTickResult:
        try:
            return self.run_tick(self._current_time())
        except Exception as exc:
            self._append_failure_event("tick", exc)
            return PipelineTickResult(0, 0, 0, 0, "failed")

    def heartbeat_now(self) -> None:
        try:
            self.heartbeat(self._current_time())
        except Exception as exc:
            self._append_failure_event("heartbeat", exc)

    def ensure_daily_compensation_now(self) -> int | None:
        try:
            return self.ensure_daily_compensation(self._current_time())
        except Exception as exc:
            self._append_failure_event("compensation", exc)
            return None

    def mark_stopping(self, now: datetime) -> None:
        self._write_heartbeat(now, "stopping")

    def mark_stopped(self, now: datetime) -> None:
        self._write_heartbeat(now, "stopped")

    def _run_stage(self, stage: str, operation: Callable[[], object]) -> int:
        try:
            result = operation()
            success_count = getattr(result, "success_count")
            if (
                isinstance(success_count, bool)
                or not isinstance(success_count, int)
                or success_count < 0
            ):
                raise ValueError("stage success_count must be nonnegative")
            return success_count
        except Exception as exc:
            self._append_failure_event(stage, exc)
            return 0

    def _run_report(self, now: datetime) -> str | None:
        try:
            request = self.report_repo.claim_next(
                now,
                self.worker_id,
                self.report_lease_seconds,
            )
            if request is None:
                return None
            result = self.report_service.execute_request(
                request,
                self.worker_id,
                now,
            )
            status = getattr(result, "status")
            return _required_text(status, "report status", 30)
        except Exception as exc:
            self._append_failure_event("report", exc)
            return "failed"

    def _append_failure_event(self, stage: str, error: Exception) -> None:
        try:
            self.event_repo.append_event(
                NewCollectionEvent(
                    job_id=None,
                    run_id=None,
                    target_run_id=None,
                    worker_id=self.worker_id,
                    level="error",
                    event_type="pipeline_stage_failed",
                    stage=stage,
                    message=_safe_exception(stage, error),
                    metrics_json=json.dumps(
                        {"exception_type": type(error).__name__},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    actor_type="worker",
                    actor_name=self.worker_id,
                )
            )
        except Exception:
            return

    def _write_heartbeat(self, now: datetime, status: str) -> None:
        _require_now(now)
        if now < self.start_time:
            raise ValueError("heartbeat now must not precede start_time")
        self.heartbeat_repo.upsert_heartbeat(
            WorkerHeartbeatRecord(
                worker_id=self.worker_id,
                worker_type="pipeline",
                hostname=self.hostname,
                process_id=self.process_id,
                version=self.version,
                status=status,
                last_heartbeat_at=now,
                start_time=self.start_time,
                last_error_summary=None,
            )
        )

    def _current_time(self) -> datetime:
        now = self.now_provider()
        _require_now(now)
        return now


def default_pipeline_worker_identity() -> tuple[str, str, int]:
    hostname = socket.gethostname()
    process_id = os.getpid()
    host_digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:16]
    unique_suffix = uuid4().hex[:12]
    worker_id = f"pipeline-{host_digest}-{process_id}-{unique_suffix}"
    return worker_id, hostname, process_id


def _safe_exception(_stage: str, _error: Exception) -> str:
    return sanitize_output(
        "后处理阶段执行失败，异常类型见结构化指标",
        maximum=500,
    )


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


def _require_now(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != APPLICATION_TIMEZONE
    ):
        raise ValueError(
            f"now must use {APPLICATION_TIMEZONE} ZoneInfo"
        )
    return value


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return value
