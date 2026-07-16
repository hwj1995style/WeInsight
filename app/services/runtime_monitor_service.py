from __future__ import annotations

from dataclasses import dataclass, replace
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import json
import math
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    PipelineType,
    RunStatus,
    ensure_schedule_datetime,
)
from app.domain.wechat_health import WechatHealthStatus
from app.storage.collection_event_repo import sanitize_output


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.PARTIAL_SUCCESS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.ABORTED,
    }
)
EVENT_LEVELS = frozenset({"debug", "info", "warning", "error"})
ACTIVE_WORKER_STATUSES = frozenset(
    {"starting", "running", "degraded", "stopping"}
)


def runtime_visibility_start(now: datetime) -> datetime:
    ensure_schedule_datetime(now, field_name="now")
    month_index = now.year * 12 + now.month - 1 - 3
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


@dataclass(frozen=True, slots=True)
class RunListFilter:
    pipeline_type: PipelineType | None = None
    status: RunStatus | None = None
    run_date: date | None = None
    job_id: int | None = None
    job_name: str | None = None


@dataclass(frozen=True, slots=True)
class EventListFilter:
    job_id: int | None = None
    run_id: int | None = None
    target_run_id: int | None = None
    pipeline_type: PipelineType | None = None
    level: str | None = None
    subject_name: str | None = None
    include_routine: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: int
    job_id: int
    job_name: str
    pipeline_type: PipelineType
    scheduled_at: datetime
    status: RunStatus
    worker_id: str | None
    start_time: datetime | None
    end_time: datetime | None
    target_total_count: int
    target_success_count: int
    target_failed_count: int


@dataclass(frozen=True, slots=True)
class TargetRunDetail:
    id: int
    job_target_id: int
    target_name: str
    status: str
    stage: str | None
    batch_id: str | None
    read_count: int
    insert_count: int
    duplicate_count: int
    skipped_count: int
    error_code: str | None
    error_summary: str | None
    screenshot_path: object
    start_time: datetime | None
    end_time: datetime | None
    feed_item_count: int = 0
    invalid_count: int = 0
    http_status: int | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class RunDetail:
    run: RunSummary
    hostname: str | None
    lease_expires_at: datetime | None
    error_code: str | None
    error_summary: str | None
    targets: tuple[TargetRunDetail, ...]


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    id: int
    job_id: int | None
    run_id: int | None
    target_run_id: int | None
    pipeline_type: PipelineType | None
    worker_id: str | None
    level: str
    event_type: str
    stage: str | None
    message: str
    metrics_summary: str
    actor_type: str
    actor_name: str
    create_time: datetime
    subject_name: str | None = None
    target_count: int = 0
    target_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeMetricItem:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class RuntimeEventView:
    event: RuntimeEvent
    summary: str
    subject: str
    metric_items: tuple[RuntimeMetricItem, ...]
    technical_metrics: str


@dataclass(frozen=True, slots=True)
class WorkerHeartbeatView:
    worker_id: str
    worker_type: str
    hostname: str
    process_id: int
    version: str
    status: str
    last_heartbeat_at: datetime
    start_time: datetime
    last_error_summary: str | None
    is_live: bool


@dataclass(frozen=True, slots=True)
class WechatHealthView:
    hostname: str
    status: WechatHealthStatus
    detected_version: str | None
    consecutive_failure_count: int
    message: str
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class UiLockView:
    state: str
    owner_pipeline: str | None = None
    owner_task_id: str | None = None
    acquire_time: datetime | None = None
    heartbeat_time: datetime | None = None
    expire_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class WorkerMonitorSnapshot:
    workers: tuple[WorkerHeartbeatView, ...]
    health_checks: tuple[WechatHealthView, ...]
    ui_lock: UiLockView
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class RunTrendBucket:
    bucket_start: datetime
    success_count: int
    partial_success_count: int
    failed_count: int
    cancelled_count: int
    aborted_count: int

    @property
    def successful_count(self) -> int:
        return self.success_count + self.partial_success_count

    @property
    def unsuccessful_count(self) -> int:
        return self.failed_count + self.aborted_count

    @property
    def terminal_total(self) -> int:
        return (
            self.successful_count
            + self.unsuccessful_count
            + self.cancelled_count
        )


@dataclass(frozen=True, slots=True)
class TodayRunCounts:
    queued: int = 0
    running: int = 0
    success: int = 0
    partial_success: int = 0
    failed: int = 0
    cancelled: int = 0
    aborted: int = 0

    @property
    def total(self) -> int:
        return sum(
            (
                self.queued,
                self.running,
                self.success,
                self.partial_success,
                self.failed,
                self.cancelled,
                self.aborted,
            )
        )


@dataclass(frozen=True, slots=True)
class RuntimeDashboardSnapshot:
    live_collector_count: int
    total_worker_count: int
    latest_wechat_status: WechatHealthStatus | None
    latest_wechat_checked_at: datetime | None
    ui_lock_state: str
    active_job_count: int
    stop_requested_job_count: int
    today_runs: TodayRunCounts
    trend: tuple[RunTrendBucket, ...]
    generated_at: datetime

    @classmethod
    def empty(cls, now: datetime) -> "RuntimeDashboardSnapshot":
        ensure_schedule_datetime(now, field_name="now")
        current = now.replace(minute=0, second=0, microsecond=0)
        return cls(
            live_collector_count=0,
            total_worker_count=0,
            latest_wechat_status=None,
            latest_wechat_checked_at=None,
            ui_lock_state="unavailable",
            active_job_count=0,
            stop_requested_job_count=0,
            today_runs=TodayRunCounts(),
            trend=tuple(
                RunTrendBucket(
                    bucket_start=current - timedelta(hours=23 - index),
                    success_count=0,
                    partial_success_count=0,
                    failed_count=0,
                    cancelled_count=0,
                    aborted_count=0,
                )
                for index in range(24)
            ),
            generated_at=now,
        )


@dataclass(frozen=True, slots=True)
class JobRuntimeHistory:
    runs: tuple[RunSummary, ...]
    events: tuple[RuntimeEvent, ...]


class RuntimeMonitorRepo(Protocol):
    def list_runs(
        self,
        filters: RunListFilter,
        page: int,
        page_size: int,
        visible_since: datetime,
    ) -> PagedResult[RunSummary]: ...

    def get_run(self, run_id: int) -> RunDetail | None: ...

    def list_events(
        self,
        filters: EventListFilter,
        page: int,
        page_size: int,
        visible_since: datetime,
    ) -> PagedResult[RuntimeEvent]: ...

    def get_worker_snapshot(
        self, now: datetime, heartbeat_ttl_seconds: int
    ) -> WorkerMonitorSnapshot: ...

    def get_dashboard_snapshot(
        self, now: datetime, heartbeat_ttl_seconds: int
    ) -> RuntimeDashboardSnapshot: ...

    def get_job_history(self, job_id: int, limit: int) -> JobRuntimeHistory: ...


class RunNotFoundError(LookupError):
    pass


class RunOutsideVisibilityError(LookupError):
    pass


class RuntimeMonitorService:
    def __init__(
        self,
        repo: RuntimeMonitorRepo,
        screenshot_root: Path,
        *,
        heartbeat_ttl_seconds: int,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(screenshot_root, Path):
            raise TypeError("screenshot_root must be Path")
        _positive_integer(heartbeat_ttl_seconds, "heartbeat_ttl_seconds")
        if now_provider is not None and not callable(now_provider):
            raise TypeError("now_provider must be callable or None")
        self.repo = repo
        self.screenshot_root = screenshot_root.resolve(strict=False)
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self.now_provider = now_provider or (
            lambda: datetime.now(ZoneInfo(APPLICATION_TIMEZONE))
        )

    def list_runs(
        self,
        filters: RunListFilter,
        page: int,
        page_size: int,
    ) -> PagedResult[RunSummary]:
        _validate_run_filters(filters)
        _page(page, page_size, maximum=100)
        visible_since = self.visible_since()
        return self.repo.list_runs(filters, page, page_size, visible_since)

    def visible_since(self) -> datetime:
        return runtime_visibility_start(self.now_provider())

    def get_run(
        self, run_id: int, *, visible_since: datetime | None = None
    ) -> RunDetail:
        _positive_integer(run_id, "run_id")
        boundary = self.visible_since() if visible_since is None else visible_since
        ensure_schedule_datetime(boundary, field_name="visible_since")
        detail = self.repo.get_run(run_id)
        if detail is None:
            raise RunNotFoundError(f"run not found: {run_id}")
        if detail.run.scheduled_at < boundary:
            raise RunOutsideVisibilityError(f"run outside visibility: {run_id}")
        return replace(
            detail,
            error_summary=_safe_optional(detail.error_summary),
            targets=tuple(self.safe_target(target) for target in detail.targets),
        )

    def list_events(
        self,
        filters: EventListFilter,
        page: int,
        page_size: int,
    ) -> PagedResult[RuntimeEvent]:
        _validate_event_filters(filters)
        _page(page, page_size, maximum=200)
        visible_since = self.visible_since()
        effective_filters = replace(
            filters,
            start_at=(
                max(filters.start_at, visible_since)
                if filters.start_at
                else visible_since
            ),
        )
        _validate_event_filters(effective_filters)
        result = self.repo.list_events(
            effective_filters, page, page_size, visible_since
        )
        return PagedResult(
            items=[_safe_event(item) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total_count=result.total_count,
        )

    def to_event_view(self, event: RuntimeEvent) -> RuntimeEventView:
        if not isinstance(event, RuntimeEvent):
            raise TypeError("event must be RuntimeEvent")
        return _event_view(event)

    def get_workers(self, now: datetime) -> WorkerMonitorSnapshot:
        ensure_schedule_datetime(now, field_name="now")
        snapshot = self.repo.get_worker_snapshot(
            now,
            self.heartbeat_ttl_seconds,
        )
        return replace(
            snapshot,
            workers=tuple(_safe_worker(item) for item in snapshot.workers),
            health_checks=tuple(
                _safe_health(item) for item in snapshot.health_checks
            ),
            ui_lock=_safe_ui_lock(snapshot.ui_lock),
        )

    def get_dashboard(self, now: datetime) -> RuntimeDashboardSnapshot:
        ensure_schedule_datetime(now, field_name="now")
        snapshot = self.repo.get_dashboard_snapshot(
            now,
            self.heartbeat_ttl_seconds,
        )
        if len(snapshot.trend) != 24:
            raise ValueError("dashboard trend must contain 24 hourly buckets")
        return snapshot

    def get_job_history(self, job_id: int, limit: int = 10) -> JobRuntimeHistory:
        _positive_integer(job_id, "job_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        history = self.repo.get_job_history(job_id, limit)
        return JobRuntimeHistory(
            runs=history.runs,
            events=tuple(_safe_event(item) for item in history.events),
        )

    def safe_screenshot_path(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            return "截图路径无效"
        try:
            candidate = Path(value)
            if not candidate.is_absolute():
                return "截图路径无效"
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(self.screenshot_root):
                return "截图路径无效"
        except (OSError, RuntimeError, ValueError):
            return "截图路径无效"
        return str(resolved)

    def safe_target(self, target: TargetRunDetail) -> TargetRunDetail:
        if not isinstance(target, TargetRunDetail):
            raise TypeError("target must be TargetRunDetail")
        return replace(
            target,
            error_summary=_safe_optional(target.error_summary),
            screenshot_path=self.safe_screenshot_path(target.screenshot_path),
        )


def runtime_event_summary(event_type: str, level: str) -> str:
    summary = _EVENT_SUMMARIES.get(event_type, "未分类事件")
    alert = {"warning": "WARN", "error": "ERROR"}.get(level)
    return f"{alert} · {summary}" if alert else summary


def _validate_run_filters(filters: object) -> None:
    if not isinstance(filters, RunListFilter):
        raise TypeError("filters must be RunListFilter")
    if filters.pipeline_type is not None and not isinstance(
        filters.pipeline_type, PipelineType
    ):
        raise ValueError("pipeline_type is invalid")
    if filters.status is not None and not isinstance(filters.status, RunStatus):
        raise ValueError("status is invalid")
    if filters.run_date is not None and type(filters.run_date) is not date:
        raise ValueError("run_date is invalid")
    _optional_identity(filters.job_id, "job_id")
    _optional_text(filters.job_name, "job_name", 200)


def _validate_event_filters(filters: object) -> None:
    if not isinstance(filters, EventListFilter):
        raise TypeError("filters must be EventListFilter")
    for field in ("job_id", "run_id", "target_run_id"):
        _optional_identity(getattr(filters, field), field)
    if filters.pipeline_type is not None and not isinstance(
        filters.pipeline_type, PipelineType
    ):
        raise ValueError("pipeline_type is invalid")
    if filters.level is not None and filters.level not in EVENT_LEVELS:
        raise ValueError("level is invalid")
    _optional_text(filters.subject_name, "subject_name", 200)
    if type(filters.include_routine) is not bool:
        raise ValueError("include_routine is invalid")
    for field in ("start_at", "end_at"):
        value = getattr(filters, field)
        if value is not None:
            ensure_schedule_datetime(value, field_name=field)
    if (
        filters.start_at is not None
        and filters.end_at is not None
        and filters.start_at > filters.end_at
    ):
        raise ValueError("start_at must not be after end_at")


def _safe_event(event: RuntimeEvent) -> RuntimeEvent:
    return replace(
        event,
        worker_id=_safe_optional_structured(event.worker_id, maximum=100),
        event_type=_safe_structured(event.event_type, maximum=100),
        stage=_safe_optional_structured(event.stage, maximum=50),
        message=sanitize_output(event.message),
        metrics_summary=_safe_metrics_summary(event.metrics_summary),
        actor_type=_safe_structured(event.actor_type, maximum=20),
        actor_name=_safe_label(event.actor_name, maximum=100),
        subject_name=_safe_optional(event.subject_name),
        target_names=tuple(
            _safe_label(name, maximum=200) for name in event.target_names
        ),
    )


_EVENT_SUMMARIES = {
    "job_created": "已创建采集任务",
    "job_stop_requested": "已请求停止采集任务",
    "job_deleted": "已删除采集任务",
    "collection_run_claimed": "已领取采集运行",
    "collection_run_started": "开始执行采集任务",
    "collection_run_finished": "本轮采集完成",
    "collection_run_lease_expired": "采集运行租约已过期",
    "collection_target_started": "开始处理目标",
    "collection_target_finished": "目标处理完成",
    "werss_authorization_settings_changed": "授权提醒配置已更新",
    "werss_authorization_settings_failed": "授权提醒配置保存失败",
    "werss_authorization_test_succeeded": "授权提醒连接测试成功",
    "werss_authorization_test_failed": "授权提醒连接测试失败",
    "misfire": "错过计划已合并执行",
    "pipeline_stage_failed": "后处理失败",
    "werss_catalog_sync_changed": "WeRSS 公众号清单已同步",
}
_METRIC_FIELDS = (
    (("executed_target_count", "target_total_count"), "目标"),
    (("target_success_count",), "成功"),
    (("target_failed_count", "failed_count"), "失败"),
    (("insert_count",), "新增"),
    (("duplicate_count",), "重复"),
    (("skipped_count",), "跳过"),
    (("read_count",), "读取"),
    (("missed_count",), "错过计划"),
)


def _event_view(event: RuntimeEvent) -> RuntimeEventView:
    summary = runtime_event_summary(event.event_type, event.level)
    id_subjects = tuple(
        f"{label} #{value}"
        for label, value in (
            ("任务", event.job_id), ("运行", event.run_id),
            ("目标", event.target_run_id),
        )
        if value is not None
    )
    type_label = {
        PipelineType.GROUP: "微信群",
        PipelineType.ARTICLE: "公众号",
    }.get(event.pipeline_type, "对象")
    if event.subject_name:
        subject = f"{type_label} · {event.subject_name}"
    elif event.target_run_id is not None:
        subject = " · ".join(id_subjects)
    elif event.run_id is not None and event.target_count == 1 and event.target_names:
        subject = f"{type_label} · {event.target_names[0]}"
    elif event.run_id is not None and event.target_count > 0:
        subject = f"{type_label} · 本轮 {event.target_count} 个目标"
    elif event.run_id is not None:
        subject = "本轮全部目标"
    else:
        subject = "系统事件"
    technical_metrics = event.metrics_summary
    try:
        metrics = json.loads(technical_metrics)
        if not isinstance(metrics, dict):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        metrics = {}
        technical_metrics = (
            technical_metrics if technical_metrics == "指标过大已截断" else "指标不可用"
        )
    items = []
    for keys, label in _METRIC_FIELDS:
        for key in keys:
            value = metrics.get(key)
            if _is_primary_metric(value):
                rendered = str(value).lower() if isinstance(value, bool) else str(value)
                items.append(RuntimeMetricItem(label, rendered))
                break
    return RuntimeEventView(
        event, summary, subject, tuple(items),
        technical_metrics,
    )


def _is_primary_metric(value: object) -> bool:
    return (
        isinstance(value, bool)
        or isinstance(value, int) and value >= 0
        or isinstance(value, float) and math.isfinite(value) and value >= 0
    )


def _safe_worker(worker: WorkerHeartbeatView) -> WorkerHeartbeatView:
    return replace(
        worker,
        worker_id=_safe_structured(worker.worker_id, maximum=100),
        worker_type=_safe_structured(worker.worker_type, maximum=30),
        hostname=_safe_structured(worker.hostname, maximum=255),
        version=_safe_structured(worker.version, maximum=100),
        status=_safe_structured(worker.status, maximum=30),
        last_error_summary=_safe_optional(worker.last_error_summary),
    )


def _safe_health(health: WechatHealthView) -> WechatHealthView:
    return replace(
        health,
        hostname=_safe_structured(health.hostname, maximum=255),
        detected_version=_safe_optional_structured(
            health.detected_version,
            maximum=100,
        ),
        message=sanitize_output(health.message),
    )


def _safe_ui_lock(lock: UiLockView) -> UiLockView:
    return replace(
        lock,
        owner_pipeline=_safe_optional_structured(
            lock.owner_pipeline,
            maximum=20,
        ),
        owner_task_id=_safe_optional_structured(
            lock.owner_task_id,
            maximum=100,
        ),
    )


def _safe_optional(value: str | None) -> str | None:
    return None if value is None else sanitize_output(value)


def _safe_label(value: str, *, maximum: int) -> str:
    return sanitize_output(str(value), maximum=maximum).strip()


def _safe_optional_label(value: str | None, *, maximum: int) -> str | None:
    return None if value is None else _safe_label(value, maximum=maximum)


def _safe_structured(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return "invalid"
    if re.fullmatch(r"[A-Za-z0-9_.:@-]+", value) is None:
        return "invalid"
    return value


def _safe_optional_structured(
    value: str | None,
    *,
    maximum: int,
) -> str | None:
    return None if value is None else _safe_structured(value, maximum=maximum)


def _safe_metrics_summary(value: object) -> str:
    try:
        decoded = json.loads(str(value))
        if not isinstance(decoded, dict):
            raise ValueError
        safe = _safe_metric_value(decoded, depth=0)
        encoded = json.dumps(
            safe,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return "指标无效"
    return encoded if len(encoded.encode("utf-8")) <= 4096 else "指标过大已截断"


def _safe_metric_value(value: object, *, depth: int) -> object:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return sanitize_output(value, maximum=200)
    if isinstance(value, dict):
        if depth >= 3:
            return "指标层级已截断"
        result = {}
        for index, (key, item) in enumerate(list(value.items())[:20]):
            safe_key = (
                key
                if isinstance(key, str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,50}", key)
                else f"field_{index}"
            )
            result[safe_key] = _safe_metric_value(item, depth=depth + 1)
        if len(value) > 20:
            result["_truncated"] = True
        return result
    if isinstance(value, list):
        if depth >= 3:
            return "指标层级已截断"
        items = [
            _safe_metric_value(item, depth=depth + 1)
            for item in value[:20]
        ]
        if len(value) > 20:
            items.append("指标条目已截断")
        return items
    return sanitize_output(str(value), maximum=200)


def _page(page: object, page_size: object, *, maximum: int) -> None:
    _positive_integer(page, "page")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= maximum
    ):
        raise ValueError(f"page_size must be between 1 and {maximum}")


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _optional_identity(value: object, field: str) -> None:
    if value is not None:
        _positive_integer(value, field)


def _optional_text(value: object, field: str, maximum: int) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError(f"{field} is invalid")
