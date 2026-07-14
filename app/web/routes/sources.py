from __future__ import annotations

from datetime import date, datetime
from time import monotonic
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services.source_management_service import (
    GroupSourceCommand,
    SourceAlreadyExistsError,
    SourceInUseError,
    SourceMustBeDisabledError,
    SourceNotFoundError,
    SourceRenameBlockedError,
)
from app.domain.article_downstream import ArticleBackfillCommand
from app.services.article_downstream_service import (
    ArticleDownstreamSourceUnavailableError,
    ArticleDownstreamValidationError,
)


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="/sources")


@router.get("/groups", response_class=HTMLResponse)
async def group_list(
    request: Request, page: int = 1, page_size: int = 20
) -> Response:
    try:
        result = await run_in_threadpool(
            request.app.state.source_service.list_groups_page,
            page,
            page_size,
        )
    except ValueError as exc:
        return _source_error_response(request, exc, "/sources/groups")
    return templates.TemplateResponse(
        request=request,
        name="sources/groups.html",
        context={
            "section": "groups",
            "groups": result.items,
            "page": result,
        },
    )


@router.get("/groups/new", response_class=HTMLResponse)
async def group_new(request: Request) -> Response:
    return _group_form_response(request, _group_defaults(), None)


@router.post("/groups", response_class=HTMLResponse)
async def group_create(request: Request) -> Response:
    try:
        values = await _form_values(request)
    except ValueError as exc:
        return _group_form_response(
            request,
            _group_defaults(),
            _form_error_message(exc),
            status_code=422,
        )
    try:
        await run_in_threadpool(
            request.app.state.source_service.create_group,
            _group_command(values),
        )
    except SourceAlreadyExistsError:
        return _group_form_response(
            request,
            values,
            "已存在同名采集名单，请使用其他名称。",
            status_code=409,
        )
    except ValueError:
        return _group_form_response(
            request,
            values,
            "请检查表单字段，群采集间隔不能少于 30 秒。",
            status_code=422,
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/groups")
    return RedirectResponse("/sources/groups", status_code=303)


@router.get("/groups/{source_id}/edit", response_class=HTMLResponse)
async def group_edit(request: Request, source_id: int) -> Response:
    try:
        source = await run_in_threadpool(
            request.app.state.source_service.get_group, source_id
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/groups")
    return _group_form_response(request, _group_values(source), None, source_id)


@router.post("/groups/{source_id}", response_class=HTMLResponse)
async def group_update(request: Request, source_id: int) -> Response:
    try:
        values = await _form_values(request)
    except ValueError as exc:
        return _group_form_response(
            request,
            _group_defaults(),
            _form_error_message(exc),
            source_id,
            status_code=422,
        )
    try:
        await run_in_threadpool(
            request.app.state.source_service.update_group,
            source_id,
            _group_command(values),
        )
    except SourceAlreadyExistsError:
        return _group_form_response(
            request,
            values,
            "已存在同名采集名单，请使用其他名称。",
            source_id,
            status_code=409,
        )
    except ValueError:
        return _group_form_response(
            request,
            values,
            "请检查表单字段，群采集间隔不能少于 30 秒。",
            source_id,
            status_code=422,
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/groups")
    return RedirectResponse("/sources/groups", status_code=303)


@router.post("/groups/{source_id}/enable", response_class=HTMLResponse)
async def group_enable(request: Request, source_id: int) -> Response:
    return await _set_enabled(request, "group", source_id, True)


@router.post("/groups/{source_id}/disable", response_class=HTMLResponse)
async def group_disable(request: Request, source_id: int) -> Response:
    return await _set_enabled(request, "group", source_id, False)


@router.post("/groups/{source_id}/delete", response_class=HTMLResponse)
async def group_delete(request: Request, source_id: int) -> Response:
    return await _delete(request, "group", source_id)


@router.get("/articles", response_class=HTMLResponse)
async def article_list(
    request: Request, page: int = 1, page_size: int = 20
) -> Response:
    try:
        result = await run_in_threadpool(
            request.app.state.article_status_service.list_page,
            page,
            page_size,
            datetime.now(),
        )
    except ValueError as exc:
        return _source_error_response(request, exc, "/sources/articles")
    start_date, end_date = request.app.state.article_downstream_service.default_backfill_dates(datetime.now())
    summary = _take_downstream_flash(request)
    return templates.TemplateResponse(
        request=request,
        name="sources/articles.html",
        context={
            "section": "articles",
            "articles": result.items,
            "page": result,
            "sync_interval_minutes": request.app.state.article_status_service.sync_interval_minutes,
            "backfill_start_date": start_date.isoformat(),
            "backfill_end_date": end_date.isoformat(),
            "backfill_summary": summary,
        },
    )


@router.post("/articles/{source_id}/downstream-processing", response_class=HTMLResponse)
async def article_downstream_processing(request: Request, source_id: int) -> Response:
    try:
        values = await _strict_form_values(request, {"enabled"})
        if values.get("enabled") not in {"0", "1"}:
            raise ValueError("invalid enabled")
        await run_in_threadpool(
            request.app.state.article_downstream_service.set_processing_enabled,
            source_id,
            values["enabled"] == "1",
        )
    except (ValueError, ArticleDownstreamValidationError) as exc:
        return _downstream_error(request, exc, 422)
    except ArticleDownstreamSourceUnavailableError as exc:
        return _downstream_error(request, exc, 404)
    return RedirectResponse("/sources/articles", status_code=303)


@router.post("/articles/downstream-processing/backfill", response_class=HTMLResponse)
async def article_downstream_backfill(request: Request) -> Response:
    try:
        values = await _strict_form_values(
            request, {"scope", "source_id", "start_date", "end_date", "mode", "confirm_force"}
        )
        scope = values.get("scope", "")
        source_id = _positive_optional_integer(values.get("source_id", "")) if scope == "single" else None
        command = ArticleBackfillCommand(
            scope=scope, source_id=source_id,
            start_date=date.fromisoformat(values.get("start_date", "")),
            end_date=date.fromisoformat(values.get("end_date", "")),
            mode=values.get("mode", ""),
            force_confirmed=_strict_checkbox(values, "confirm_force"),
        )
        if command.mode == "force_analyze" and not command.force_confirmed:
            raise ArticleDownstreamValidationError("force_analyze requires explicit confirmation")
        summary = await run_in_threadpool(
            request.app.state.article_downstream_service.backfill, command, datetime.now()
        )
    except (ValueError, ArticleDownstreamValidationError) as exc:
        return _downstream_error(request, exc, 422)
    except ArticleDownstreamSourceUnavailableError as exc:
        return _downstream_error(request, exc, 404)
    _set_downstream_flash(request, summary)
    return RedirectResponse("/sources/articles", status_code=303)


async def _set_enabled(
    request: Request,
    source_type: str,
    source_id: int,
    enabled: bool,
) -> Response:
    service = request.app.state.source_service
    return_url = _return_url(source_type)
    try:
        await run_in_threadpool(service.set_group_enabled, source_id, enabled)
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, return_url)
    return RedirectResponse(return_url, status_code=303)


async def _delete(
    request: Request, source_type: str, source_id: int
) -> Response:
    service = request.app.state.source_service
    return_url = _return_url(source_type)
    try:
        await run_in_threadpool(service.delete_group, source_id)
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, return_url)
    return RedirectResponse(return_url, status_code=303)


def _source_error_response(
    request: Request,
    exc: Exception,
    return_url: str,
) -> Response:
    status_code = 409
    job_names: tuple[str, ...] = ()
    if isinstance(exc, SourceNotFoundError):
        status_code = 404
        message = "采集名单不存在或已被删除。"
    elif isinstance(exc, ValueError):
        status_code = 422
        message = "请检查表单字段后重试。"
    elif isinstance(exc, SourceMustBeDisabledError):
        message = "删除前请先停用该采集名单。"
    elif isinstance(exc, SourceAlreadyExistsError):
        message = "已存在同名采集名单，请使用其他名称。"
    elif isinstance(exc, SourceRenameBlockedError):
        job_names = exc.job_names
        message = "该名单已有采集历史或任务引用，不能改名。"
    else:
        job_names = exc.job_names  # type: ignore[union-attr]
        message = "该名单正被采集任务引用，当前操作无法完成。"
    return templates.TemplateResponse(
        request=request,
        name="sources/error.html",
        context={
            "section": "groups" if return_url.endswith("groups") else "articles",
            "message": message,
            "job_names": job_names,
            "return_url": return_url,
        },
        status_code=status_code,
    )


async def _form_values(request: Request) -> dict[str, str]:
    form = await request.form()
    values: dict[str, str] = {}
    for key, value in form.multi_items():
        if key in values:
            raise ValueError("duplicate form field")
        if not isinstance(value, str):
            raise ValueError("invalid form field")
        values[key] = value
    values.pop("csrf_token", None)
    return values


async def _strict_form_values(request: Request, allowed: set[str]) -> dict[str, str]:
    values = await _form_values(request)
    if set(values) - allowed:
        raise ValueError("unknown form field")
    return values


def _positive_optional_integer(value: str) -> int:
    if not value or value.strip() != value:
        raise ValueError("invalid source_id")
    parsed = int(value)
    if parsed < 1:
        raise ValueError("invalid source_id")
    return parsed


def _strict_checkbox(values: dict[str, str], field: str) -> bool:
    if field not in values:
        return False
    if values[field] != "1":
        raise ValueError("invalid checkbox")
    return True


_SUMMARY_FIELDS = (
    "matched_article_count", "clean_task_created_count", "clean_task_recovered_count",
    "analyze_task_created_count", "analyze_task_recovered_count",
    "existing_result_skipped_count", "running_task_skipped_count", "out_of_scope_skipped_count",
)
_FLASH_TTL_SECONDS = 300.0
_FLASH_CAPACITY = 128


def _flash_key(request: Request) -> str | None:
    return request.cookies.get(request.app.state.config.auth.session_cookie_name)


def _set_downstream_flash(request: Request, summary: object) -> None:
    key = _flash_key(request)
    if key:
        store = request.app.state.article_downstream_flashes
        now = monotonic()
        _prune_downstream_flashes(store, now)
        store.pop(key, None)
        store[key] = (now + _FLASH_TTL_SECONDS, {
            name: min(max(int(getattr(summary, name)), 0), 1_000_000_000)
            for name in _SUMMARY_FIELDS
        })
        _prune_downstream_flashes(store, now)


def _take_downstream_flash(request: Request) -> dict[str, int] | None:
    key = _flash_key(request)
    if not key:
        return None
    store = request.app.state.article_downstream_flashes
    now = monotonic()
    _prune_downstream_flashes(store, now)
    entry = store.pop(key, None)
    return entry[1] if entry is not None else None


def _prune_downstream_flashes(store: object, now: float) -> None:
    expired = [key for key, (expires_at, _) in store.items() if expires_at <= now]
    for key in expired:
        store.pop(key, None)
    while len(store) > _FLASH_CAPACITY:
        store.popitem(last=False)


def _downstream_error(request: Request, exc: Exception, status_code: int) -> Response:
    message = "公众号不可用于下游处理。" if status_code == 404 else "请检查下游处理表单字段后重试。"
    if "confirmation" in str(exc):
        message = "强制重新分析前必须确认风险。"
    return templates.TemplateResponse(
        request=request, name="sources/error.html",
        context={"section": "articles", "message": message, "job_names": (), "return_url": "/sources/articles"},
        status_code=status_code,
    )


def _group_command(values: dict[str, str]) -> GroupSourceCommand:
    return GroupSourceCommand(
        group_name=values.get("group_name", ""),
        is_core_group=_checked(values, "is_core_group"),
        priority=_integer(values, "priority"),
        poll_interval_seconds=_integer(values, "poll_interval_seconds"),
        backtrack_pages=_integer(values, "backtrack_pages"),
        extra_backtrack_pages=_integer(values, "extra_backtrack_pages"),
        remark=_optional(values, "remark"),
    )


def _integer(values: dict[str, str], field: str) -> int:
    value = values.get(field, "")
    if not value or value.strip() != value:
        raise ValueError(f"invalid integer: {field}")
    return int(value)


def _checked(values: dict[str, str], field: str) -> bool:
    if field not in values:
        return False
    value = values[field]
    if value not in {"on", "1", "true"}:
        raise ValueError("invalid checkbox field")
    return True


def _optional(values: dict[str, str], field: str) -> str | None:
    value = values.get(field, "")
    return value if value else None


def _group_defaults() -> dict[str, object]:
    return {
        "group_name": "",
        "is_core_group": False,
        "priority": 10,
        "poll_interval_seconds": 30,
        "backtrack_pages": 10,
        "extra_backtrack_pages": 30,
        "remark": "",
    }


def _group_values(source) -> dict[str, object]:
    return {
        "group_name": source.group_name,
        "is_core_group": source.is_core_group,
        "priority": source.priority,
        "poll_interval_seconds": source.poll_interval_seconds,
        "backtrack_pages": source.backtrack_pages,
        "extra_backtrack_pages": source.extra_backtrack_pages,
        "remark": source.remark or "",
    }


def _group_form_response(
    request: Request,
    values: dict[str, object],
    error: str | None,
    source_id: int | None = None,
    *,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="sources/group_form.html",
        context={
            "section": "groups",
            "values": values,
            "error": error,
            "source_id": source_id,
        },
        status_code=status_code,
    )


def _form_error_message(exc: ValueError) -> str:
    if str(exc) == "duplicate form field":
        return "表单包含重复字段，请刷新页面后重试。"
    return "请检查表单字段后重试。"


def _return_url(source_type: str) -> str:
    return "/sources/groups" if source_type == "group" else "/sources/articles"


_SOURCE_ERRORS = (
    SourceNotFoundError,
    SourceAlreadyExistsError,
    SourceMustBeDisabledError,
    SourceInUseError,
    SourceRenameBlockedError,
    ValueError,
)
