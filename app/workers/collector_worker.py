from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    PipelineType,
    RunStatus,
)
from app.pipelines.article_polling_runner import (
    ArticlePollingRunResult,
    ArticlePollingTarget,
)
from app.pipelines.group_polling_runner import (
    GroupPollingRunResult,
    GroupPollingTarget,
)
from app.storage.collection_event_repo import (
    NewCollectionEvent,
    sanitize_output,
)
from app.storage.collection_runtime_repo import (
    ClaimedCollectionRun,
    ClaimedTarget,
    TargetRunOutcome,
)
from app.storage.worker_heartbeat_repo import WorkerHeartbeatRecord


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_GROUP_SNAPSHOT_FIELDS = frozenset(
    {
        "poll_interval_seconds",
        "backtrack_pages",
        "extra_backtrack_pages",
        "is_core_group",
        "remark",
    }
)
_ARTICLE_SNAPSHOT_FIELDS = frozenset(
    {
        "account_type",
        "poll_interval_minutes",
        "daily_window_start",
        "daily_window_end",
        "max_articles_per_round",
        "collect_today_only",
        "dedup_key",
        "remark",
    }
)
_USE_CURRENT_ERROR = object()


@dataclass(frozen=True, slots=True)
class CollectorTickResult:
    status: str
    run_id: int | None
    pipeline_type: PipelineType | None
    executed_target_count: int


class RuntimeRepo(Protocol):
    def claim_next_due(self, now, worker_id, lease_seconds): ...
    def heartbeat_run(self, run_id, worker_id, now, lease_seconds): ...
    def is_stop_requested(self, job_id): ...
    def start_target(self, run_id, job_target_id, batch_id, now): ...
    def finish_target(self, target_run_id, outcome, now): ...
    def cancel_queued_targets(self, run_id, now): ...
    def finish_run(self, run_id, status, now): ...
    def abort_expired_runs(self, now): ...


class EventRepo(Protocol):
    def append_event(self, event: NewCollectionEvent) -> int: ...


class HeartbeatRepo(Protocol):
    def upsert_heartbeat(self, record: WorkerHeartbeatRecord) -> None: ...
    def register_collector_start(
        self, record: WorkerHeartbeatRecord, now: datetime, ttl_seconds: int
    ) -> bool: ...


class HealthMonitor(Protocol):
    def can_collect(self, now: datetime) -> bool: ...
    def run_check(self, now: datetime): ...


class SingleTargetRunner(Protocol):
    def run_once(self, now: datetime): ...


class ManagedCollectorWorker:
    def __init__(
        self,
        *,
        runtime_repo: RuntimeRepo,
        event_repo: EventRepo,
        heartbeat_repo: HeartbeatRepo,
        health_monitor: HealthMonitor,
        group_runner_factory: Callable[
            [GroupPollingTarget, str], SingleTargetRunner
        ],
        article_runner_factory: Callable[
            [ArticlePollingTarget, str, Callable[[], bool]],
            SingleTargetRunner,
        ],
        worker_id: str,
        hostname: str,
        process_id: int,
        version: str,
        start_time: datetime,
        run_lease_seconds: int,
        batch_id_factory: Callable[
            [ClaimedCollectionRun, ClaimedTarget], str
        ]
        | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        _required_text(worker_id, "worker_id", 100)
        _required_text(hostname, "hostname", 255)
        _positive_integer(process_id, "process_id")
        _required_text(version, "version", 100)
        _require_now(start_time)
        _positive_integer(run_lease_seconds, "run_lease_seconds")
        self.runtime_repo = runtime_repo
        self.event_repo = event_repo
        self.heartbeat_repo = heartbeat_repo
        self.health_monitor = health_monitor
        self.group_runner_factory = group_runner_factory
        self.article_runner_factory = article_runner_factory
        self.worker_id = worker_id
        self.hostname = hostname
        self.process_id = process_id
        self.version = version
        self.start_time = start_time
        self.run_lease_seconds = run_lease_seconds
        self.batch_id_factory = batch_id_factory or _default_batch_id
        self.now_provider = now_provider or _shanghai_now
        self._state_lock = threading.Lock()
        self._active_run_id: int | None = None
        self._lease_lost = False
        self._degraded = False
        self._registered = False
        self._heartbeat_status = "starting"
        self._last_error_summary: str | None = None
        self._shutdown = threading.Event()

    @property
    def status(self) -> str:
        with self._state_lock:
            if self._shutdown.is_set():
                return self._heartbeat_status
            if self._degraded:
                return "degraded"
            return self._heartbeat_status

    def register_start(self, now: datetime, ttl_seconds: int) -> bool:
        _require_now(now)
        _positive_integer(ttl_seconds, "ttl_seconds")
        record = self._heartbeat_record(now, status="starting")
        registered = self.heartbeat_repo.register_collector_start(
            record, now, ttl_seconds
        )
        with self._state_lock:
            self._registered = registered is True
            if self._registered:
                self._heartbeat_status = "running"
        return registered is True

    def run_tick(self, now: datetime) -> CollectorTickResult:
        _require_now(now)
        with self._state_lock:
            registered = self._registered
            degraded = self._degraded
        if not registered:
            return _tick("not_registered")
        if self._shutdown.is_set():
            return _tick("stopping")
        if degraded:
            return _tick("degraded")
        if not self.health_monitor.can_collect(now):
            return _tick("paused_unhealthy")
        try:
            run = self.runtime_repo.claim_next_due(
                now, self.worker_id, self.run_lease_seconds
            )
        except Exception as exc:
            self._mark_degraded("claim failed", exc)
            return _tick("degraded")
        if run is None:
            return _tick("idle")
        self._append_event(
            run,
            level="info",
            event_type="collection_run_claimed",
            stage="claim",
            message="collection run claimed by managed worker",
            metrics={"target_count": len(run.targets)},
        )
        return self.execute_run(run, now)

    def execute_run(
        self,
        run: ClaimedCollectionRun,
        now: datetime,
    ) -> CollectorTickResult:
        _require_now(now)
        if not isinstance(run, ClaimedCollectionRun):
            raise TypeError("run must be ClaimedCollectionRun")
        self._activate_run(run.run_id)
        executed = 0
        outcomes: list[str] = []
        stopped = False
        try:
            stopped = self._stop_requested(run)
            for item in sorted(
                run.targets,
                key=lambda value: (
                    value.priority,
                    value.source_name,
                    value.job_target_id,
                ),
            ):
                if stopped:
                    break
                batch_id = self.batch_id_factory(run, item)
                _required_text(batch_id, "batch_id", 64)
                target_run_id = self.runtime_repo.start_target(
                    run.run_id,
                    item.job_target_id,
                    batch_id,
                    now,
                )
                self._append_target_event(
                    run,
                    target_run_id,
                    level="info",
                    event_type="collection_target_started",
                    message="collection target started",
                    metrics={"job_target_id": item.job_target_id},
                )
                outcome = self._execute_target(
                    run, item, batch_id, target_run_id, now
                )
                target_finished_at = self._current_time()
                self.runtime_repo.finish_target(
                    target_run_id, outcome, target_finished_at
                )
                self._append_target_event(
                    run,
                    target_run_id,
                    level=("error" if outcome.status == "failed" else "info"),
                    event_type="collection_target_finished",
                    message=f"collection target finished with {outcome.status}",
                    metrics={
                        "read_count": outcome.read_count,
                        "insert_count": outcome.insert_count,
                        "duplicate_count": outcome.duplicate_count,
                        "skipped_count": outcome.skipped_count,
                    },
                )
                executed += 1
                outcomes.append(outcome.status)
                stopped = (
                    outcome.status == "cancelled"
                    or self._stop_requested(run)
                )

            run_finished_at = self._current_time()
            if stopped:
                self.runtime_repo.cancel_queued_targets(
                    run.run_id, run_finished_at
                )
                final_status = RunStatus.CANCELLED
            else:
                final_status = _final_run_status(outcomes)
            self.runtime_repo.finish_run(
                run.run_id, final_status, run_finished_at
            )
            self._append_event(
                run,
                level=("warning" if final_status is RunStatus.CANCELLED else "info"),
                event_type="collection_run_finished",
                stage="finish",
                message=f"collection run finished with {final_status.value}",
                metrics={"executed_target_count": executed},
            )
            return CollectorTickResult(
                status=final_status.value,
                run_id=run.run_id,
                pipeline_type=run.pipeline_type,
                executed_target_count=executed,
            )
        finally:
            self._clear_active_run(run.run_id)

    def heartbeat(self, now: datetime) -> None:
        _require_now(now)
        with self._state_lock:
            active_run_id = self._active_run_id
        active_lease_failed = False
        if active_run_id is not None:
            try:
                lease_ok = self.runtime_repo.heartbeat_run(
                    active_run_id,
                    self.worker_id,
                    now,
                    self.run_lease_seconds,
                )
            except Exception as exc:
                lease_ok = False
                active_lease_failed = self._mark_active_degraded(
                    active_run_id,
                    "active run lease refresh failed",
                    exc,
                )
            if lease_ok is not True:
                active_lease_failed = (
                    self._mark_lease_lost(active_run_id)
                    or active_lease_failed
                )
        with self._state_lock:
            stopping = self._heartbeat_status in {"stopping", "stopped"}
            active_still_current = (
                active_run_id is not None
                and self._active_run_id == active_run_id
            )
            active_is_degraded = active_still_current and self._degraded
            status = (
                self._heartbeat_status
                if stopping
                else (
                    "degraded"
                    if active_lease_failed or active_is_degraded
                    else "running"
                )
            )
        record = self._heartbeat_record(
            now,
            status=status,
            last_error_override=(
                _USE_CURRENT_ERROR if status == "degraded" else None
            ),
        )
        try:
            self.heartbeat_repo.upsert_heartbeat(record)
        except Exception as exc:
            self._mark_degraded("worker heartbeat write failed", exc)
            raise
        if status == "running":
            with self._state_lock:
                self._degraded = False
                self._heartbeat_status = "running"
                self._last_error_summary = None

    def heartbeat_now(self) -> None:
        self.heartbeat(self.now_provider())

    def health_check_now(self):
        now = self.now_provider()
        _require_now(now)
        return self.health_monitor.run_check(now)

    def recover_expired_now(self) -> int:
        now = self.now_provider()
        _require_now(now)
        return int(self.runtime_repo.abort_expired_runs(now))

    def request_shutdown(self) -> None:
        self._shutdown.set()
        with self._state_lock:
            self._heartbeat_status = "stopping"

    def is_shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    def mark_stopping(self, now: datetime) -> None:
        _require_now(now)
        self._shutdown.set()
        with self._state_lock:
            self._heartbeat_status = "stopping"
        self.heartbeat_repo.upsert_heartbeat(
            self._heartbeat_record(now, status="stopping")
        )

    def mark_stopped(self, now: datetime) -> None:
        _require_now(now)
        self._shutdown.set()
        with self._state_lock:
            self._heartbeat_status = "stopped"
        self.heartbeat_repo.upsert_heartbeat(
            self._heartbeat_record(now, status="stopped")
        )

    def _execute_target(
        self,
        run: ClaimedCollectionRun,
        item: ClaimedTarget,
        batch_id: str,
        target_run_id: int,
        now: datetime,
    ) -> TargetRunOutcome:
        try:
            if run.pipeline_type is PipelineType.GROUP:
                polling_target = _group_target(item)
                runner = self.group_runner_factory(polling_target, batch_id)
            elif run.pipeline_type is PipelineType.ARTICLE:
                polling_target = _article_target(item)
                runner = self.article_runner_factory(
                    polling_target,
                    batch_id,
                    lambda: self._stop_requested(run),
                )
            else:  # pragma: no cover - enum construction prevents this
                raise ValueError("unsupported pipeline type")
        except SnapshotValidationError:
            return TargetRunOutcome(
                status="failed",
                error_code="INVALID_TARGET_SNAPSHOT",
                error_summary="target snapshot validation failed",
            )
        except Exception as exc:
            return TargetRunOutcome(
                status="failed",
                error_code="RUNNER_BUILD_ERROR",
                error_summary=_safe_exception("runner build failed", exc),
            )
        try:
            result = runner.run_once(now)
        except Exception as exc:
            return TargetRunOutcome(
                status="failed",
                error_code="RUNNER_EXECUTION_ERROR",
                error_summary=_safe_exception("runner execution failed", exc),
            )
        try:
            if run.pipeline_type is PipelineType.GROUP:
                return _group_outcome(result)
            return _article_outcome(result)
        except Exception as exc:
            return TargetRunOutcome(
                status="failed",
                error_code="RUNNER_RESULT_ERROR",
                error_summary=_safe_exception("runner result invalid", exc),
            )

    def _stop_requested(self, run: ClaimedCollectionRun) -> bool:
        if self._shutdown.is_set():
            return True
        with self._state_lock:
            if self._degraded or (
                self._active_run_id == run.run_id and self._lease_lost
            ):
                return True
        try:
            return self.runtime_repo.is_stop_requested(run.job_id) is True
        except Exception as exc:
            self._mark_degraded("stop check failed", exc)
            return True

    def _activate_run(self, run_id: int) -> None:
        _positive_integer(run_id, "run_id")
        with self._state_lock:
            if self._active_run_id is not None:
                raise RuntimeError("collector already has an active run")
            self._active_run_id = run_id
            self._lease_lost = False

    def _clear_active_run(self, run_id: int) -> None:
        with self._state_lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
                self._lease_lost = False

    def _mark_lease_lost(self, run_id: int) -> bool:
        with self._state_lock:
            if self._active_run_id != run_id:
                return False
            self._lease_lost = True
            self._degraded = True
            self._heartbeat_status = "degraded"
            self._last_error_summary = "active run lease ownership was lost"
            return True

    def _mark_active_degraded(
        self,
        run_id: int,
        context: str,
        error: Exception,
    ) -> bool:
        summary = _safe_exception(context, error)
        with self._state_lock:
            if self._active_run_id != run_id:
                return False
            self._lease_lost = True
            self._degraded = True
            self._heartbeat_status = "degraded"
            self._last_error_summary = summary
            return True

    def _current_time(self) -> datetime:
        now = self.now_provider()
        _require_now(now)
        return now

    def _mark_degraded(self, context: str, error: Exception) -> None:
        summary = _safe_exception(context, error)
        with self._state_lock:
            self._degraded = True
            self._heartbeat_status = "degraded"
            self._last_error_summary = summary

    def _heartbeat_record(
        self,
        now: datetime,
        *,
        status: str,
        last_error_override=_USE_CURRENT_ERROR,
    ) -> WorkerHeartbeatRecord:
        with self._state_lock:
            last_error = (
                self._last_error_summary
                if last_error_override is _USE_CURRENT_ERROR
                else last_error_override
            )
        return WorkerHeartbeatRecord(
            worker_id=self.worker_id,
            worker_type="collector",
            hostname=self.hostname,
            process_id=self.process_id,
            version=self.version,
            status=status,
            last_heartbeat_at=now,
            start_time=self.start_time,
            last_error_summary=last_error,
        )

    def _append_event(
        self,
        run: ClaimedCollectionRun,
        *,
        level: str,
        event_type: str,
        stage: str,
        message: str,
        metrics: dict[str, object],
    ) -> None:
        self.event_repo.append_event(
            NewCollectionEvent(
                job_id=run.job_id,
                run_id=run.run_id,
                target_run_id=None,
                worker_id=self.worker_id,
                level=level,
                event_type=event_type,
                stage=stage,
                message=sanitize_output(message),
                metrics_json=json.dumps(
                    metrics,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                actor_type="worker",
                actor_name=self.worker_id,
            )
        )

    def _append_target_event(
        self,
        run: ClaimedCollectionRun,
        target_run_id: int,
        *,
        level: str,
        event_type: str,
        message: str,
        metrics: dict[str, object],
    ) -> None:
        self.event_repo.append_event(
            NewCollectionEvent(
                job_id=run.job_id,
                run_id=run.run_id,
                target_run_id=target_run_id,
                worker_id=self.worker_id,
                level=level,
                event_type=event_type,
                stage="target",
                message=sanitize_output(message),
                metrics_json=json.dumps(
                    metrics,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                actor_type="worker",
                actor_name=self.worker_id,
            )
        )


class SnapshotValidationError(ValueError):
    pass


def _group_target(item: ClaimedTarget) -> GroupPollingTarget:
    data = _snapshot_object(item.config_snapshot_json, _GROUP_SNAPSHOT_FIELDS)
    poll_interval = _snapshot_positive_int(data, "poll_interval_seconds")
    _snapshot_positive_int(data, "backtrack_pages")
    _snapshot_positive_int(data, "extra_backtrack_pages")
    if type(data["is_core_group"]) is not bool:
        raise SnapshotValidationError("is_core_group must be bool")
    _snapshot_optional_text(data["remark"], "remark", 500)
    _claimed_identity(item)
    return GroupPollingTarget(
        group_name=item.source_name,
        priority=item.priority,
        poll_interval_seconds=poll_interval,
    )


def _article_target(item: ClaimedTarget) -> ArticlePollingTarget:
    data = _snapshot_object(item.config_snapshot_json, _ARTICLE_SNAPSHOT_FIELDS)
    if data["account_type"] not in {"official", "subscription"}:
        raise SnapshotValidationError("account_type is invalid")
    poll_interval = _snapshot_positive_int(data, "poll_interval_minutes")
    max_articles = _snapshot_positive_int(data, "max_articles_per_round")
    _snapshot_time(data, "daily_window_start")
    _snapshot_time(data, "daily_window_end")
    if type(data["collect_today_only"]) is not bool:
        raise SnapshotValidationError("collect_today_only must be bool")
    _snapshot_required_text(data["dedup_key"], "dedup_key", 50)
    _snapshot_optional_text(data["remark"], "remark", 500)
    _claimed_identity(item)
    return ArticlePollingTarget(
        account_name=item.source_name,
        priority=item.priority,
        poll_interval_minutes=poll_interval,
        max_articles_per_round=max_articles,
    )


def _snapshot_object(raw: str, expected_fields: frozenset[str]) -> dict:
    if not isinstance(raw, str):
        raise SnapshotValidationError("snapshot must be JSON text")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError("snapshot must be valid JSON") from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError("snapshot must be a JSON object")
    if frozenset(value) != expected_fields:
        raise SnapshotValidationError("snapshot fields do not match schema")
    return value


def _claimed_identity(item: ClaimedTarget) -> None:
    _positive_integer(item.job_target_id, "job_target_id")
    _positive_integer(item.source_id, "source_id")
    _positive_integer(item.priority, "priority")
    _required_text(item.source_name, "source_name", 200)


def _snapshot_positive_int(data: dict, field: str) -> int:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SnapshotValidationError(f"{field} must be a positive integer")
    return value


def _snapshot_time(data: dict, field: str) -> time:
    value = data[field]
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{field} must be a time string")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotValidationError(f"{field} must be a time string") from exc
    if parsed.tzinfo is not None:
        raise SnapshotValidationError(f"{field} must be naive")
    return parsed


def _snapshot_required_text(
    value: object, field: str, maximum: int
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise SnapshotValidationError(f"{field} is invalid")
    return value


def _snapshot_optional_text(value: object, field: str, maximum: int) -> None:
    if value is not None:
        _snapshot_required_text(value, field, maximum)


def _group_outcome(result: object) -> TargetRunOutcome:
    if not isinstance(result, GroupPollingRunResult):
        raise TypeError("group runner returned invalid result")
    failed = result.failed_count > 0 or result.lock_timeout_count > 0
    return TargetRunOutcome(
        status="failed" if failed else "success",
        read_count=result.read_count,
        insert_count=result.insert_count,
        duplicate_count=result.duplicate_count,
        error_code=result.error_code,
        error_summary=_optional_safe(result.error_summary),
        screenshot_path=result.screenshot_path,
    )


def _article_outcome(result: object) -> TargetRunOutcome:
    if not isinstance(result, ArticlePollingRunResult):
        raise TypeError("article runner returned invalid result")
    if result.stop_requested_count > 0:
        status = "cancelled"
    elif result.failed_count > 0 or result.lock_timeout_count > 0:
        status = "failed"
    elif result.core_group_interrupted_count > 0 or (
        result.skipped_count > 0 and result.success_count == 0
    ):
        status = "skipped"
    elif result.success_count > 0:
        status = "success"
    else:
        status = "failed"
    return TargetRunOutcome(
        status=status,
        read_count=result.link_count,
        insert_count=result.raw_insert_count,
        duplicate_count=result.duplicate_count,
        skipped_count=result.skipped_count + result.core_group_interrupted_count,
        error_code=result.error_code,
        error_summary=_optional_safe(result.error_summary),
        screenshot_path=result.screenshot_path,
    )


def _final_run_status(outcomes: list[str]) -> RunStatus:
    failed = outcomes.count("failed")
    completed = sum(value in {"success", "skipped"} for value in outcomes)
    if failed and completed:
        return RunStatus.PARTIAL_SUCCESS
    if failed:
        return RunStatus.FAILED
    if completed and completed == len(outcomes):
        return RunStatus.SUCCESS
    return RunStatus.FAILED


def _optional_safe(value: str | None) -> str | None:
    return None if value is None else sanitize_output(value, maximum=1000)


def _safe_exception(context: str, error: Exception) -> str:
    detail = sanitize_output(str(error), maximum=800).strip()
    return sanitize_output(
        context if not detail else f"{context}: {detail}",
        maximum=1000,
    )


def _tick(status: str) -> CollectorTickResult:
    return CollectorTickResult(status, None, None, 0)


def _default_batch_id(
    run: ClaimedCollectionRun, item: ClaimedTarget
) -> str:
    prefix = "group" if run.pipeline_type is PipelineType.GROUP else "article"
    return f"{prefix}-{run.run_id}-{item.job_target_id}-{uuid4().hex[:12]}"


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


def _require_now(value: object) -> None:
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if (
        not isinstance(value.tzinfo, ZoneInfo)
        or value.tzinfo.key != APPLICATION_TIMEZONE
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"now must use {APPLICATION_TIMEZONE} ZoneInfo"
        )


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def default_worker_identity() -> tuple[str, str, int]:
    hostname = socket.gethostname()
    process_id = os.getpid()
    host_digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:16]
    unique_suffix = uuid4().hex[:12]
    worker_id = f"collector-{host_digest}-{process_id}-{unique_suffix}"
    return worker_id, hostname, process_id
