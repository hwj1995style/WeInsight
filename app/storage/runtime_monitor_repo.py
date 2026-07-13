from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import APPLICATION_TIMEZONE, PipelineType, RunStatus
from app.domain.wechat_health import WechatHealthStatus
from app.services.runtime_monitor_service import (
    ACTIVE_WORKER_STATUSES,
    EventListFilter,
    JobRuntimeHistory,
    RunDetail,
    RunListFilter,
    RunSummary,
    RunTrendBucket,
    RuntimeDashboardSnapshot,
    RuntimeEvent,
    TargetRunDetail,
    TodayRunCounts,
    UiLockView,
    WechatHealthView,
    WorkerHeartbeatView,
    WorkerMonitorSnapshot,
)
from app.storage.collection_event_repo import sanitize_output


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_TARGET_STATUSES = frozenset(
    {"queued", "running", "success", "failed", "skipped", "cancelled"}
)
_KNOWN_RUN_STATUSES = tuple(status.value for status in RunStatus)
_TERMINAL_VALUES = frozenset(
    {"success", "partial_success", "failed", "cancelled", "aborted"}
)


class MysqlRuntimeMonitorRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_runs(
        self,
        filters: RunListFilter,
        page: int,
        page_size: int,
        visible_since: datetime,
    ) -> PagedResult[RunSummary]:
        where, params = _run_filter_clause(filters, visible_since)
        count_statement = text(
            f"""
            SELECT COUNT(*)
            FROM wechat_collection_job_run run
            INNER JOIN wechat_collection_job job ON job.id = run.job_id
            {where}
            """
        )
        data_statement = text(
            f"""
            SELECT
                run.id, run.job_id, job.job_name, job.pipeline_type,
                run.scheduled_at, run.status, run.worker_id,
                run.start_time, run.end_time, run.target_total_count,
                run.target_success_count, run.target_failed_count
            FROM wechat_collection_job_run run
            INNER JOIN wechat_collection_job job ON job.id = run.job_id
            {where}
            ORDER BY run.scheduled_at DESC, run.id DESC
            LIMIT :limit OFFSET :offset
            """
        )
        data_params = {
            **params,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        with self.engine.begin() as connection:
            total = int(connection.execute(count_statement, params).scalar_one())
            rows = connection.execute(
                data_statement,
                data_params,
            ).mappings().all()
        return PagedResult(
            items=[_run_summary(row) for row in rows],
            page=page,
            page_size=page_size,
            total_count=total,
        )

    def get_run(self, run_id: int) -> RunDetail | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                _RUN_DETAIL,
                {"run_id": run_id},
            ).mappings().first()
            if row is None:
                return None
            target_rows = connection.execute(
                _RUN_TARGETS,
                {"run_id": run_id},
            ).mappings().all()
        return RunDetail(
            run=_run_summary(row),
            hostname=_optional_text(row.get("hostname")),
            lease_expires_at=_optional_db_datetime(row.get("lease_expires_at")),
            error_code=_optional_text(row.get("error_code")),
            error_summary=_safe_optional(row.get("error_summary")),
            targets=tuple(_target_detail(item) for item in target_rows),
        )

    def list_events(
        self,
        filters: EventListFilter,
        page: int,
        page_size: int,
        visible_since: datetime,
    ) -> PagedResult[RuntimeEvent]:
        where, params = _event_filter_clause(filters, visible_since)
        count_statement = text(
            f"""
            SELECT COUNT(*)
            FROM wechat_collection_job_event event
            LEFT JOIN wechat_collection_job job ON job.id = event.job_id
            {where}
            """
        )
        data_statement = text(
            f"""
            SELECT
                event.id, event.job_id, event.run_id, event.target_run_id,
                job.pipeline_type, event.worker_id, event.level,
                event.event_type, event.stage, event.message,
                event.metrics_json, event.actor_type, event.actor_name,
                event.create_time
            FROM wechat_collection_job_event event
            LEFT JOIN wechat_collection_job job ON job.id = event.job_id
            {where}
            ORDER BY event.id DESC
            LIMIT :limit OFFSET :offset
            """
        )
        data_params = {
            **params,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        with self.engine.begin() as connection:
            total = int(connection.execute(count_statement, params).scalar_one())
            rows = connection.execute(data_statement, data_params).mappings().all()
        return PagedResult(
            items=[_runtime_event(row) for row in rows],
            page=page,
            page_size=page_size,
            total_count=total,
        )

    def get_worker_snapshot(
        self,
        now: datetime,
        heartbeat_ttl_seconds: int,
    ) -> WorkerMonitorSnapshot:
        cutoff = _to_db_datetime(now - timedelta(seconds=heartbeat_ttl_seconds))
        with self.engine.begin() as connection:
            worker_rows = connection.execute(
                _WORKERS,
                {"cutoff": cutoff},
            ).mappings().all()
            health_rows = connection.execute(_LATEST_HEALTH).mappings().all()
        return WorkerMonitorSnapshot(
            workers=tuple(_worker_view(row) for row in worker_rows),
            health_checks=tuple(_health_view(row) for row in health_rows),
            ui_lock=UiLockView(state="unavailable"),
            checked_at=now,
        )

    def get_dashboard_snapshot(
        self,
        now: datetime,
        heartbeat_ttl_seconds: int,
    ) -> RuntimeDashboardSnapshot:
        workers = self.get_worker_snapshot(now, heartbeat_ttl_seconds)
        today_start = datetime.combine(now.date(), time.min, tzinfo=_ZONE)
        today_end = today_start + timedelta(days=1)
        trend_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        trend_start = trend_end - timedelta(hours=24)
        with self.engine.begin() as connection:
            job_row = connection.execute(_JOB_COUNTS).mappings().one()
            today_rows = connection.execute(
                _TODAY_RUNS,
                {
                    "today_start": _to_db_datetime(today_start),
                    "today_end": _to_db_datetime(today_end),
                },
            ).mappings().all()
            trend_rows = connection.execute(
                _TREND_RUNS,
                {
                    "trend_start": _to_db_datetime(trend_start),
                    "trend_end": _to_db_datetime(trend_end),
                },
            ).mappings().all()
        today = _today_counts(today_rows)
        latest_health = max(
            workers.health_checks,
            key=lambda item: item.checked_at,
            default=None,
        )
        return RuntimeDashboardSnapshot(
            live_collector_count=sum(
                item.worker_type == "collector" and item.is_live
                for item in workers.workers
            ),
            total_worker_count=len(workers.workers),
            latest_wechat_status=(
                None if latest_health is None else latest_health.status
            ),
            latest_wechat_checked_at=(
                None if latest_health is None else latest_health.checked_at
            ),
            ui_lock_state=workers.ui_lock.state,
            active_job_count=int(job_row.get("active_count") or 0),
            stop_requested_job_count=int(
                job_row.get("stop_requested_count") or 0
            ),
            today_runs=today,
            trend=_fill_trend(trend_rows, now),
            generated_at=now,
        )

    def get_job_history(self, job_id: int, limit: int) -> JobRuntimeHistory:
        runs = self.list_runs(
            RunListFilter(job_id=job_id),
            page=1,
            page_size=limit,
            visible_since=datetime(1000, 1, 1, tzinfo=_ZONE),
        )
        events = self.list_events(
            EventListFilter(job_id=job_id),
            page=1,
            page_size=limit,
            visible_since=datetime(1000, 1, 1, tzinfo=_ZONE),
        )
        return JobRuntimeHistory(
            runs=tuple(runs.items),
            events=tuple(events.items),
        )


def _run_filter_clause(
    filters: RunListFilter,
    visible_since: datetime,
) -> tuple[str, dict[str, object]]:
    conditions = ["run.scheduled_at >= :visible_since"]
    params: dict[str, object] = {"visible_since": _to_db_datetime(visible_since)}
    if filters.pipeline_type is not None:
        conditions.append("job.pipeline_type = :pipeline_type")
        params["pipeline_type"] = filters.pipeline_type.value
    if filters.status is not None:
        conditions.append("run.status = :status")
        params["status"] = filters.status.value
    if filters.run_date is not None:
        conditions.extend(
            (
                "run.scheduled_at >= :date_start",
                "run.scheduled_at < :date_end",
            )
        )
        params["date_start"] = datetime.combine(filters.run_date, time.min)
        params["date_end"] = datetime.combine(
            filters.run_date + timedelta(days=1), time.min
        )
    if filters.job_id is not None:
        conditions.append("run.job_id = :job_id")
        params["job_id"] = filters.job_id
    if filters.job_name is not None:
        conditions.append("job.job_name LIKE :job_name ESCAPE '\\\\'")
        params["job_name"] = f"%{_escape_like(filters.job_name)}%"
    where = "" if not conditions else "WHERE " + " AND ".join(conditions)
    return where, params


def _event_filter_clause(
    filters: EventListFilter,
    visible_since: datetime,
) -> tuple[str, dict[str, object]]:
    conditions = ["event.create_time >= :visible_since"]
    params: dict[str, object] = {"visible_since": _to_db_datetime(visible_since)}
    for field in ("job_id", "run_id", "target_run_id"):
        value = getattr(filters, field)
        if value is not None:
            conditions.append(f"event.{field} = :{field}")
            params[field] = value
    if filters.pipeline_type is not None:
        conditions.append("job.pipeline_type = :pipeline_type")
        params["pipeline_type"] = filters.pipeline_type.value
    if filters.level is not None:
        conditions.append("event.level = :level")
        params["level"] = filters.level
    if filters.start_at is not None:
        conditions.append("event.create_time >= :start_at")
        params["start_at"] = _to_db_datetime(filters.start_at)
    if filters.end_at is not None:
        conditions.append("event.create_time <= :end_at")
        params["end_at"] = _to_db_datetime(filters.end_at)
    where = "" if not conditions else "WHERE " + " AND ".join(conditions)
    return where, params


def _fill_trend(rows, now: datetime) -> tuple[RunTrendBucket, ...]:
    current = now.replace(minute=0, second=0, microsecond=0)
    start = current - timedelta(hours=23)
    values: dict[tuple[datetime, str], int] = {}
    for row in rows:
        status = str(row["status"])
        if status not in _TERMINAL_VALUES:
            continue
        bucket = _db_datetime(row["bucket_start"]).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        if not start <= bucket <= current:
            continue
        values[(bucket, status)] = int(row["count"] or 0)
    return tuple(
        RunTrendBucket(
            bucket_start=bucket,
            success_count=values.get((bucket, "success"), 0),
            partial_success_count=values.get(
                (bucket, "partial_success"), 0
            ),
            failed_count=values.get((bucket, "failed"), 0),
            cancelled_count=values.get((bucket, "cancelled"), 0),
            aborted_count=values.get((bucket, "aborted"), 0),
        )
        for bucket in (start + timedelta(hours=index) for index in range(24))
    )


def _run_summary(row) -> RunSummary:
    return RunSummary(
        id=int(row["id"]),
        job_id=int(row["job_id"]),
        job_name=str(row["job_name"]),
        pipeline_type=PipelineType(str(row["pipeline_type"])),
        scheduled_at=_db_datetime(row["scheduled_at"]),
        status=RunStatus(str(row["status"])),
        worker_id=_optional_text(row.get("worker_id")),
        start_time=_optional_db_datetime(row.get("start_time")),
        end_time=_optional_db_datetime(row.get("end_time")),
        target_total_count=_nonnegative(row["target_total_count"]),
        target_success_count=_nonnegative(row["target_success_count"]),
        target_failed_count=_nonnegative(row["target_failed_count"]),
    )


def _target_detail(row) -> TargetRunDetail:
    status = str(row["status"])
    if status not in _TARGET_STATUSES:
        raise ValueError("target status is invalid")
    return TargetRunDetail(
        id=int(row["id"]),
        job_target_id=int(row["job_target_id"]),
        target_name=str(row["target_name_snapshot"]),
        status=status,
        stage=_optional_text(row.get("stage")),
        batch_id=_optional_text(row.get("batch_id")),
        read_count=_nonnegative(row["read_count"]),
        insert_count=_nonnegative(row["insert_count"]),
        duplicate_count=_nonnegative(row["duplicate_count"]),
        skipped_count=_nonnegative(row["skipped_count"]),
        error_code=_optional_text(row.get("error_code")),
        error_summary=_safe_optional(row.get("error_summary")),
        screenshot_path=row.get("screenshot_path"),
        start_time=_optional_db_datetime(row.get("start_time")),
        end_time=_optional_db_datetime(row.get("end_time")),
        feed_item_count=_nonnegative(row.get("feed_item_count", 0)),
        invalid_count=_nonnegative(row.get("invalid_count", 0)),
        http_status=_optional_int(row.get("http_status")),
        elapsed_ms=_nonnegative(row.get("elapsed_ms", 0)),
    )


def _runtime_event(row) -> RuntimeEvent:
    pipeline = row.get("pipeline_type")
    return RuntimeEvent(
        id=int(row["id"]),
        job_id=_optional_int(row.get("job_id")),
        run_id=_optional_int(row.get("run_id")),
        target_run_id=_optional_int(row.get("target_run_id")),
        pipeline_type=(None if pipeline is None else PipelineType(str(pipeline))),
        worker_id=_optional_text(row.get("worker_id")),
        level=str(row["level"]),
        event_type=str(row["event_type"]),
        stage=_optional_text(row.get("stage")),
        message=sanitize_output(str(row.get("message") or "")),
        metrics_summary=_safe_metrics(row.get("metrics_json")),
        actor_type=str(row["actor_type"]),
        actor_name=str(row.get("actor_name") or ""),
        create_time=_db_datetime(row["create_time"]),
    )


def _worker_view(row) -> WorkerHeartbeatView:
    status = str(row["status"])
    return WorkerHeartbeatView(
        worker_id=str(row["worker_id"]),
        worker_type=str(row["worker_type"]),
        hostname=str(row["hostname"]),
        process_id=int(row["process_id"]),
        version=str(row.get("version") or ""),
        status=status,
        last_heartbeat_at=_db_datetime(row["last_heartbeat_at"]),
        start_time=_db_datetime(row["start_time"]),
        last_error_summary=_safe_optional(row.get("last_error_summary")),
        is_live=(
            status in ACTIVE_WORKER_STATUSES and bool(row.get("within_ttl"))
        ),
    )


def _health_view(row) -> WechatHealthView:
    return WechatHealthView(
        hostname=str(row["hostname"]),
        status=WechatHealthStatus(str(row["status"])),
        detected_version=_safe_optional(row.get("detected_version")),
        consecutive_failure_count=_nonnegative(
            row["consecutive_failure_count"]
        ),
        message=sanitize_output(str(row.get("message") or "")),
        checked_at=_db_datetime(row["checked_at"]),
    )


def _today_counts(rows) -> TodayRunCounts:
    counts = {status: 0 for status in _KNOWN_RUN_STATUSES}
    for row in rows:
        status = str(row["status"])
        if status in counts:
            counts[status] = int(row["count"] or 0)
    return TodayRunCounts(**counts)


def _safe_metrics(value: object) -> str:
    if value is None:
        return "{}"
    try:
        decoded = json.loads(str(value))
        if not isinstance(decoded, dict):
            raise ValueError
        safe = _safe_metric_value(decoded, depth=0)
        canonical = json.dumps(
            safe,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return "指标无效"
    if len(canonical.encode("utf-8")) > 4096:
        return '{"summary":"指标过大已截断"}'
    return canonical


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _safe_optional(value: object) -> str | None:
    if value is None:
        return None
    return sanitize_output(str(value))


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _nonnegative(value: object) -> int:
    result = int(value or 0)
    if result < 0:
        raise ValueError("count must be non-negative")
    return result


def _db_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database datetime must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


def _optional_db_datetime(value: object) -> datetime | None:
    return None if value is None else _db_datetime(value)


def _to_db_datetime(value: datetime) -> datetime:
    return value.astimezone(_ZONE).replace(tzinfo=None)


_RUN_DETAIL = text(
    """
    SELECT
        run.id, run.job_id, job.job_name, job.pipeline_type,
        run.scheduled_at, run.status, run.worker_id,
        heartbeat.hostname, run.lease_expires_at,
        run.start_time, run.end_time, run.target_total_count,
        run.target_success_count, run.target_failed_count,
        run.error_code, run.error_summary
    FROM wechat_collection_job_run run
    INNER JOIN wechat_collection_job job ON job.id = run.job_id
    LEFT JOIN wechat_worker_heartbeat heartbeat
      ON heartbeat.worker_id = run.worker_id
    WHERE run.id = :run_id
    """
)

_RUN_TARGETS = text(
    """
    SELECT
        target_run.id, target_run.job_target_id,
        target.target_name_snapshot, target_run.status,
        target_run.stage, target_run.batch_id,
        target_run.read_count, target_run.insert_count,
        target_run.duplicate_count, target_run.skipped_count,
        target_run.error_code, target_run.error_summary,
        target_run.screenshot_path, target_run.start_time,
        target_run.end_time,
        COALESCE(article_log.feed_item_count, 0) AS feed_item_count,
        COALESCE(article_log.invalid_count, 0) AS invalid_count,
        article_log.http_status,
        COALESCE(article_log.elapsed_ms, 0) AS elapsed_ms
    FROM wechat_collection_job_target_run target_run
    INNER JOIN wechat_collection_job_target target
      ON target.id = target_run.job_target_id
    LEFT JOIN wechat_article_collect_log article_log
      ON article_log.id = (
          SELECT MAX(latest_log.id)
          FROM wechat_article_collect_log latest_log
          WHERE latest_log.batch_id = target_run.batch_id
            AND latest_log.account_name = target.target_name_snapshot
      )
    WHERE target_run.run_id = :run_id
    ORDER BY target.priority_snapshot ASC,
             target.target_name_snapshot ASC,
             target_run.id ASC
    """
)

_WORKERS = text(
    """
    SELECT
        worker_id, worker_type, hostname, process_id, version, status,
        last_heartbeat_at, start_time, last_error_summary,
        CASE WHEN last_heartbeat_at >= :cutoff THEN 1 ELSE 0 END AS within_ttl
    FROM wechat_worker_heartbeat
    ORDER BY worker_type ASC, hostname ASC, worker_id ASC
    """
)

_LATEST_HEALTH = text(
    """
    SELECT
        ranked.hostname, ranked.status, ranked.detected_version,
        ranked.consecutive_failure_count, ranked.message, ranked.checked_at
    FROM (
        SELECT health.*,
               ROW_NUMBER() OVER (
                   PARTITION BY hostname
                   ORDER BY checked_at DESC, id DESC
               ) AS row_rank
        FROM wechat_client_health_check health
    ) ranked
    WHERE ranked.row_rank = 1
    ORDER BY ranked.hostname ASC
    """
)

_JOB_COUNTS = text(
    """
    SELECT
        COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0)
            AS active_count,
        COALESCE(SUM(CASE WHEN status = 'stop_requested' THEN 1 ELSE 0 END), 0)
            AS stop_requested_count
    FROM wechat_collection_job
    WHERE deleted_at IS NULL
    """
)

_TODAY_RUNS = text(
    """
    SELECT status, COUNT(*) AS count
    FROM wechat_collection_job_run
    WHERE scheduled_at >= :today_start
      AND scheduled_at < :today_end
      AND status IN (
          'queued', 'running', 'success', 'partial_success',
          'failed', 'cancelled', 'aborted'
      )
    GROUP BY status
    """
)

_TREND_RUNS = text(
    """
    SELECT
        TIMESTAMP(DATE(end_time), MAKETIME(HOUR(end_time), 0, 0))
            AS bucket_start,
        status,
        COUNT(*) AS count
    FROM wechat_collection_job_run
    WHERE end_time >= :trend_start
      AND end_time < :trend_end
      AND status IN (
          'success', 'partial_success', 'failed', 'cancelled', 'aborted'
      )
    GROUP BY bucket_start, status
    ORDER BY bucket_start ASC, status ASC
    """
)
