from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType, RunStatus
from app.services.runtime_monitor_service import (
    EventListFilter,
    RunListFilter,
    RunDeletionNotAllowedError,
    RunNotFoundError,
    RunOutsideVisibilityError,
)
from app.web.pagination import build_pagination


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="/runs")

_QUERY_FIELDS = frozenset(
    {"pipeline", "status", "date", "job_id", "name", "page", "page_size"}
)
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_POSITIVE_PATTERN = re.compile(r"[1-9][0-9]*")
_DELETE_FIELDS = frozenset({"csrf_token", "confirm_delete"})

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
    return await _render_run_detail(request, run_id)


@router.post("/{run_id}/delete", response_class=HTMLResponse)
async def run_delete(request: Request, run_id: int) -> Response:
    try:
        values = await _strict_form_values(request, _DELETE_FIELDS)
        if values["confirm_delete"] != "1":
            raise ValueError("run deletion is not confirmed")
    except (KeyError, ValueError):
        return _detail_error_response(
            request,
            "请检查删除参数后重试。",
            status_code=422,
        )
    try:
        await run_in_threadpool(
            request.app.state.runtime_monitor_service.delete_terminal_run,
            run_id,
            request.state.admin.username,
            datetime.now(ZoneInfo(request.app.state.config.app.timezone)),
        )
    except RunNotFoundError:
        return _detail_error_response(
            request,
            "运行实例不存在。",
            status_code=404,
        )
    except RunDeletionNotAllowedError:
        return await _render_run_detail(
            request,
            run_id,
            error="当前运行状态不允许删除，页面已刷新。",
            status_code=409,
        )
    return RedirectResponse("/runs", status_code=303)


async def _render_run_detail(
    request: Request,
    run_id: int,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
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
    except RunOutsideVisibilityError:
        return _detail_error_response(request, "该记录已超出可查看范围")
    except (RunNotFoundError, TypeError, ValueError):
        return _detail_error_response(request, "运行实例不存在。")
    initial_events = tuple(
        request.app.state.runtime_monitor_service.to_event_view(event)
        for event in reversed(events.items)
    )
    initial_event_id = max(
        (view.event.id for view in initial_events),
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
            "error": error,
            "pipeline_labels": PIPELINE_LABELS,
            "run_status_labels": RUN_STATUS_LABELS,
        },
        status_code=status_code,
    )


def _detail_error_response(
    request: Request,
    error: str,
    *,
    status_code: int = 404,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="runs/detail.html",
        context={
            "section": "runs",
            "detail": None,
            "events": (),
            "initial_event_id": None,
            "error": error,
            "pipeline_labels": PIPELINE_LABELS,
            "run_status_labels": RUN_STATUS_LABELS,
        },
        status_code=status_code,
    )


def _list_response(
    request: Request,
    result: PagedResult,
    values: dict[str, str],
    error: str | None = None,
    *,
    status_code: int = 200,
) -> Response:
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
            "pagination": build_pagination(
                "/runs", values, page=result.page,
                page_size=result.page_size, total_count=result.total_count,
            ),
            "pagination_label": "运行分页",
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


async def _strict_form_values(
    request: Request,
    allowed: frozenset[str],
) -> dict[str, str]:
    form = await request.form()
    collected: dict[str, list[str]] = {}
    for key, value in form.multi_items():
        if key not in allowed or not isinstance(value, str):
            raise ValueError("invalid form field")
        collected.setdefault(key, []).append(value)
    if set(collected) != set(allowed):
        raise ValueError("missing form field")
    if any(len(values) != 1 for values in collected.values()):
        raise ValueError("duplicate form field")
    return {key: values[0] for key, values in collected.items()}
