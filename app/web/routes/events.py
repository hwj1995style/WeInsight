from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType
from app.services.runtime_monitor_service import EVENT_LEVELS, EventListFilter
from app.storage.collection_event_repo import CollectionEvent, sanitize_output


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()

_PAGE_FIELDS = frozenset(
    {
        "job_id",
        "run_id",
        "target_id",
        "pipeline",
        "level",
        "start",
        "end",
        "page",
        "page_size",
    }
)
_STREAM_FIELDS = frozenset({"run_id", "after_id"})
_POSITIVE_PATTERN = re.compile(r"[1-9][0-9]*")
_NONNEGATIVE_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)")
_LOCAL_DATETIME_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
)


@router.get("/events", response_class=HTMLResponse)
async def event_list(request: Request) -> Response:
    try:
        values = _single_query_values(request, _PAGE_FIELDS)
        zone = ZoneInfo(request.app.state.config.app.timezone)
        filters = EventListFilter(
            job_id=_optional_positive(values.get("job_id"), "job_id"),
            run_id=_optional_positive(values.get("run_id"), "run_id"),
            target_run_id=_optional_positive(
                values.get("target_id"), "target_id"
            ),
            pipeline_type=_optional_pipeline(values.get("pipeline")),
            level=_optional_level(values.get("level")),
            start_at=_optional_local_datetime(values.get("start"), zone),
            end_at=_optional_local_datetime(values.get("end"), zone),
        )
        if (
            filters.start_at is not None
            and filters.end_at is not None
            and filters.start_at > filters.end_at
        ):
            raise ValueError("start must not be after end")
        page = _positive(values.get("page", "1"), "page")
        page_size = _positive(values.get("page_size", "50"), "page_size")
        if page_size > 200:
            raise ValueError("page_size must be at most 200")
        result = await run_in_threadpool(
            request.app.state.runtime_monitor_service.list_events,
            filters,
            page,
            page_size,
        )
    except (TypeError, ValueError):
        return _event_list_response(
            request,
            PagedResult([], 1, 50, 0),
            _empty_values(),
            error="请检查日志筛选条件后重试。",
            status_code=422,
        )
    normalized = {
        field: values.get(field, "")
        for field in (
            "job_id",
            "run_id",
            "target_id",
            "pipeline",
            "level",
            "start",
            "end",
        )
    }
    normalized["page_size"] = str(page_size)
    return _event_list_response(request, result, normalized)


@router.get("/events/stream")
async def event_stream(request: Request) -> StreamingResponse:
    try:
        run_id, after_id = _stream_parameters(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid event cursor") from exc
    stream = CollectionEventStream(
        request=request,
        event_repo=request.app.state.event_repo,
        run_id=run_id,
        after_id=after_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


class CollectionEventStream:
    def __init__(
        self,
        *,
        request: Request,
        event_repo,
        run_id: int | None,
        after_id: int | None,
        poll_seconds: float = 1.0,
        keepalive_seconds: float = 15.0,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_polls: int | None = None,
    ) -> None:
        self.request = request
        self.event_repo = event_repo
        self.run_id = run_id
        self.after_id = after_id
        self.poll_seconds = poll_seconds
        self.keepalive_seconds = keepalive_seconds
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.max_polls = max_polls

    def __aiter__(self) -> AsyncIterator[str]:
        return self._generate()

    async def _generate(self) -> AsyncIterator[str]:
        last_emit_at = self.monotonic()
        polls = 0
        while self.max_polls is None or polls < self.max_polls:
            if await self.request.is_disconnected():
                return
            events = await run_in_threadpool(
                self.event_repo.list_events,
                self.run_id,
                self.after_id,
                200,
            )
            polls += 1
            if events:
                for event in events:
                    self.after_id = event.id
                    yield _format_sse_event(event)
                last_emit_at = self.monotonic()
            elif self.monotonic() - last_emit_at >= self.keepalive_seconds:
                yield ": keepalive\n\n"
                last_emit_at = self.monotonic()
            if self.max_polls is not None and polls >= self.max_polls:
                return
            await self.sleeper(self.poll_seconds)


def _format_sse_event(event: CollectionEvent) -> str:
    try:
        metrics = json.loads(event.metrics_json)
        if not isinstance(metrics, dict):
            metrics = {}
    except (TypeError, ValueError, json.JSONDecodeError):
        metrics = {}
    metrics = _safe_metrics_payload(metrics)
    data = json.dumps(
        {
            "level": (
                event.level.upper()
                if event.level in EVENT_LEVELS
                else "ERROR"
            ),
            "event_type": _structured_label(
                event.event_type,
                maximum=100,
                fallback="invalid_event",
            ),
            "stage": (
                None
                if event.stage is None
                else _structured_label(
                    event.stage,
                    maximum=50,
                    fallback="invalid_stage",
                )
            ),
            "message": sanitize_output(event.message),
            "metrics": metrics,
            "job_id": event.job_id,
            "run_id": event.run_id,
            "target_run_id": event.target_run_id,
            "create_time": event.create_time.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"id: {event.id}\nevent: collection\ndata: {data}\n\n"


def _stream_parameters(request: Request) -> tuple[int | None, int | None]:
    values = _single_query_values(request, _STREAM_FIELDS)
    run_id = _optional_positive(values.get("run_id"), "run_id")
    query_after = _optional_nonnegative(values.get("after_id"), "after_id")
    header = request.headers.get("last-event-id")
    header_after = (
        None if header is None else _nonnegative(header, "Last-Event-ID")
    )
    return run_id, header_after if header_after is not None else query_after


def _event_list_response(
    request: Request,
    result: PagedResult,
    values: dict[str, str],
    error: str | None = None,
    *,
    status_code: int = 200,
) -> Response:
    previous_url = None
    next_url = None
    if result.page > 1:
        previous_url = _event_list_url(values, result.page - 1)
    if result.page * result.page_size < result.total_count:
        next_url = _event_list_url(values, result.page + 1)
    return templates.TemplateResponse(
        request=request,
        name="events/index.html",
        context={
            "section": "events",
            "events": result.items,
            "page": result,
            "values": values,
            "error": error,
            "previous_url": previous_url,
            "next_url": next_url,
        },
        status_code=status_code,
    )


def _single_query_values(
    request: Request,
    allowed: frozenset[str],
) -> dict[str, str]:
    collected: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed:
            raise ValueError("unknown query field")
        collected.setdefault(key, []).append(value)
    if any(len(items) != 1 for items in collected.values()):
        raise ValueError("duplicate query field")
    return {key: items[0] for key, items in collected.items()}


def _positive(value: str, field: str) -> int:
    if _POSITIVE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a positive integer")
    return int(value)


def _optional_positive(value: str | None, field: str) -> int | None:
    return None if value in {None, ""} else _positive(value, field)


def _nonnegative(value: str, field: str) -> int:
    if _NONNEGATIVE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a nonnegative integer")
    return int(value)


def _optional_nonnegative(value: str | None, field: str) -> int | None:
    return None if value is None else _nonnegative(value, field)


def _optional_pipeline(value: str | None) -> PipelineType | None:
    if value in {None, ""}:
        return None
    try:
        return PipelineType(value)
    except ValueError as exc:
        raise ValueError("invalid pipeline") from exc


def _optional_level(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    if value not in EVENT_LEVELS:
        raise ValueError("invalid event level")
    return value


def _optional_local_datetime(
    value: str | None,
    zone: ZoneInfo,
) -> datetime | None:
    if value in {None, ""}:
        return None
    if _LOCAL_DATETIME_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid local datetime")
    try:
        return datetime.fromisoformat(value).replace(tzinfo=zone)
    except ValueError as exc:
        raise ValueError("invalid local datetime") from exc


def _event_list_url(values: dict[str, str], page: int) -> str:
    query = {
        **{key: value for key, value in values.items() if value},
        "page": str(page),
    }
    return "/events?" + urlencode(query)


def _empty_values() -> dict[str, str]:
    return {
        "job_id": "",
        "run_id": "",
        "target_id": "",
        "pipeline": "",
        "level": "",
        "start": "",
        "end": "",
        "page_size": "50",
    }


def _structured_label(value: object, *, maximum: int, fallback: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None:
        return fallback
    return value


def _safe_metrics_payload(value: object) -> dict[str, object]:
    safe = _safe_metric_value(value, depth=0)
    if not isinstance(safe, dict):
        safe = {}
    encoded = json.dumps(
        safe,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(encoded.encode("utf-8")) > 4096:
        return {"summary": "指标过大已截断"}
    return safe


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
        result: dict[str, object] = {}
        items = list(value.items())
        for index, (key, item) in enumerate(items[:20]):
            safe_key = _metric_key(key, index)
            result[safe_key] = _safe_metric_value(item, depth=depth + 1)
        if len(items) > 20:
            result["_truncated"] = True
        return result
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return "指标层级已截断"
        items = [
            _safe_metric_value(item, depth=depth + 1)
            for item in list(value)[:20]
        ]
        if len(value) > 20:
            items.append("指标条目已截断")
        return items
    return sanitize_output(str(value), maximum=200)


def _metric_key(value: object, index: int) -> str:
    if isinstance(value, str) and re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,50}", value
    ):
        return value
    return f"field_{index}"
