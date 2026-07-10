from __future__ import annotations

import re
from datetime import date as Date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType, RunStatus
from app.services.runtime_monitor_service import (
    EventListFilter,
    RunListFilter,
    RunNotFoundError,
)


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="/runs")

_QUERY_FIELDS = frozenset(
    {"pipeline", "status", "date", "job_id", "name", "page", "page_size"}
)
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_POSITIVE_PATTERN = re.compile(r"[1-9][0-9]*")

PIPELINE_LABELS = {
    PipelineType.GROUP: "微信群",
    PipelineType.ARTICLE: "公众号",
}
RUN_STATUS_LABELS = {
    RunStatus.QUEUED: "排队中",
    RunStatus.RUNNING: "运行中",
    RunStatus.SUCCESS: "成功",
    RunStatus.PARTIAL_SUCCESS: "部分成功",
    RunStatus.FAILED: "失败",
    RunStatus.CANCELLED: "已取消",
    RunStatus.ABORTED: "异常终止",
}


@router.get("", response_class=HTMLResponse)
async def run_list(request: Request) -> Response:
    try:
        values = _single_query_values(request, _QUERY_FIELDS)
        filters = RunListFilter(
            pipeline_type=_optional_pipeline(values.get("pipeline")),
            status=_optional_status(values.get("status")),
            run_date=_optional_date(values.get("date")),
            job_id=_optional_positive(values.get("job_id"), "job_id"),
            job_name=_optional_name(values.get("name")),
        )
        page = _positive(values.get("page", "1"), "page")
        page_size = _positive(values.get("page_size", "20"), "page_size")
        if page_size > 100:
            raise ValueError("page_size must be at most 100")
        result = await run_in_threadpool(
            request.app.state.runtime_monitor_service.list_runs,
            filters,
            page,
            page_size,
        )
    except (TypeError, ValueError):
        return _list_response(
            request,
            PagedResult([], 1, 20, 0),
            _empty_values(),
            error="请检查运行筛选条件后重试。",
            status_code=422,
        )
    normalized = {
        "pipeline": values.get("pipeline", ""),
        "status": values.get("status", ""),
        "date": values.get("date", ""),
        "job_id": values.get("job_id", ""),
        "name": values.get("name", ""),
        "page_size": str(page_size),
    }
    return _list_response(request, result, normalized)


@router.get("/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: int) -> Response:
    try:
        detail = await run_in_threadpool(
            request.app.state.runtime_monitor_service.get_run,
            run_id,
        )
        events = await run_in_threadpool(
            request.app.state.runtime_monitor_service.list_events,
            EventListFilter(run_id=run_id),
            1,
            50,
        )
    except (RunNotFoundError, TypeError, ValueError):
        return templates.TemplateResponse(
            request=request,
            name="runs/detail.html",
            context={
                "section": "runs",
                "detail": None,
                "events": (),
                "initial_event_id": None,
                "error": "运行实例不存在。",
                "pipeline_labels": PIPELINE_LABELS,
                "run_status_labels": RUN_STATUS_LABELS,
            },
            status_code=404,
        )
    initial_events = tuple(reversed(events.items))
    initial_event_id = max(
        (event.id for event in initial_events),
        default=None,
    )
    return templates.TemplateResponse(
        request=request,
        name="runs/detail.html",
        context={
            "section": "runs",
            "detail": detail,
            "events": initial_events,
            "initial_event_id": initial_event_id,
            "error": None,
            "pipeline_labels": PIPELINE_LABELS,
            "run_status_labels": RUN_STATUS_LABELS,
        },
    )


def _list_response(
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
        previous_url = _list_url(values, result.page - 1)
    if result.page * result.page_size < result.total_count:
        next_url = _list_url(values, result.page + 1)
    return templates.TemplateResponse(
        request=request,
        name="runs/index.html",
        context={
            "section": "runs",
            "runs": result.items,
            "page": result,
            "values": values,
            "error": error,
            "pipeline_labels": PIPELINE_LABELS,
            "run_status_labels": RUN_STATUS_LABELS,
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
    if any(len(values) != 1 for values in collected.values()):
        raise ValueError("duplicate query field")
    return {key: values[0] for key, values in collected.items()}


def _optional_pipeline(value: str | None) -> PipelineType | None:
    if value in {None, ""}:
        return None
    try:
        return PipelineType(value)
    except ValueError as exc:
        raise ValueError("invalid pipeline") from exc


def _optional_status(value: str | None) -> RunStatus | None:
    if value in {None, ""}:
        return None
    try:
        return RunStatus(value)
    except ValueError as exc:
        raise ValueError("invalid run status") from exc


def _optional_date(value: str | None) -> Date | None:
    if value in {None, ""}:
        return None
    if _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid date")
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid date") from exc


def _optional_positive(value: str | None, field: str) -> int | None:
    return None if value in {None, ""} else _positive(value, field)


def _positive(value: str, field: str) -> int:
    if _POSITIVE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a positive integer")
    return int(value)


def _optional_name(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    if len(value) > 200:
        raise ValueError("name is too long")
    return value


def _list_url(values: dict[str, str], page: int) -> str:
    query = {
        **{key: value for key, value in values.items() if value},
        "page": str(page),
    }
    return "/runs?" + urlencode(query)


def _empty_values() -> dict[str, str]:
    return {
        "pipeline": "",
        "status": "",
        "date": "",
        "job_id": "",
        "name": "",
        "page_size": "20",
    }
