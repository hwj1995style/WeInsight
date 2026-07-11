from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services.source_management_service import (
    ArticleSourceCommand,
    GroupSourceCommand,
    SourceAlreadyExistsError,
    SourceInUseError,
    SourceMustBeDisabledError,
    SourceNotFoundError,
    SourceRenameBlockedError,
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
            request.app.state.source_service.list_articles_page,
            page,
            page_size,
        )
    except ValueError as exc:
        return _source_error_response(request, exc, "/sources/articles")
    return templates.TemplateResponse(
        request=request,
        name="sources/articles.html",
        context={
            "section": "articles",
            "articles": result.items,
            "page": result,
        },
    )


@router.get("/articles/new", response_class=HTMLResponse)
async def article_new(request: Request) -> Response:
    return _article_form_response(request, _article_defaults(), None)


@router.post("/articles", response_class=HTMLResponse)
async def article_create(request: Request) -> Response:
    try:
        values = await _form_values(request)
    except ValueError as exc:
        return _article_form_response(
            request,
            _article_defaults(),
            _form_error_message(exc),
            status_code=422,
        )
    try:
        command = _article_command(values)
        await run_in_threadpool(
            request.app.state.source_service.create_article, command
        )
    except SourceAlreadyExistsError:
        return _article_form_response(
            request,
            values,
            "已存在同名采集名单，请使用其他名称。",
            status_code=409,
        )
    except ValueError:
        return _article_form_response(
            request,
            values,
            _article_validation_message(values),
            status_code=422,
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/articles")
    return RedirectResponse("/sources/articles", status_code=303)


@router.get("/articles/{source_id}/edit", response_class=HTMLResponse)
async def article_edit(request: Request, source_id: int) -> Response:
    try:
        source = await run_in_threadpool(
            request.app.state.source_service.get_article, source_id
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/articles")
    return _article_form_response(
        request,
        _article_values(source),
        None,
        source_id,
    )


@router.post("/articles/{source_id}", response_class=HTMLResponse)
async def article_update(request: Request, source_id: int) -> Response:
    try:
        values = await _form_values(request)
    except ValueError as exc:
        return _article_form_response(
            request,
            _article_defaults(),
            _form_error_message(exc),
            source_id,
            status_code=422,
        )
    try:
        await run_in_threadpool(
            request.app.state.source_service.update_article,
            source_id,
            _article_command(values),
        )
    except SourceAlreadyExistsError:
        return _article_form_response(
            request,
            values,
            "已存在同名采集名单，请使用其他名称。",
            source_id,
            status_code=409,
        )
    except ValueError:
        return _article_form_response(
            request,
            values,
            _article_validation_message(values),
            source_id,
            status_code=422,
        )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, "/sources/articles")
    return RedirectResponse("/sources/articles", status_code=303)


@router.post("/articles/{source_id}/enable", response_class=HTMLResponse)
async def article_enable(request: Request, source_id: int) -> Response:
    return await _set_enabled(request, "article", source_id, True)


@router.post("/articles/{source_id}/disable", response_class=HTMLResponse)
async def article_disable(request: Request, source_id: int) -> Response:
    return await _set_enabled(request, "article", source_id, False)


@router.post("/articles/{source_id}/delete", response_class=HTMLResponse)
async def article_delete(request: Request, source_id: int) -> Response:
    return await _delete(request, "article", source_id)


async def _set_enabled(
    request: Request,
    source_type: str,
    source_id: int,
    enabled: bool,
) -> Response:
    service = request.app.state.source_service
    return_url = _return_url(source_type)
    try:
        if source_type == "group":
            await run_in_threadpool(
                service.set_group_enabled, source_id, enabled
            )
        else:
            await run_in_threadpool(
                service.set_article_enabled, source_id, enabled
            )
    except _SOURCE_ERRORS as exc:
        return _source_error_response(request, exc, return_url)
    return RedirectResponse(return_url, status_code=303)


async def _delete(
    request: Request, source_type: str, source_id: int
) -> Response:
    service = request.app.state.source_service
    return_url = _return_url(source_type)
    try:
        if source_type == "group":
            await run_in_threadpool(service.delete_group, source_id)
        else:
            await run_in_threadpool(service.delete_article, source_id)
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
        if key == "csrf_token":
            continue
        if key in values:
            raise ValueError("duplicate form field")
        if not isinstance(value, str):
            raise ValueError("invalid form field")
        values[key] = value
    return values


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


def _article_command(values: dict[str, str]) -> ArticleSourceCommand:
    return ArticleSourceCommand(
        account_name=values.get("account_name", ""),
        account_type=values.get("account_type", ""),
        feed_url=values.get("feed_url", ""),
        request_timeout_seconds=_integer(values, "request_timeout_seconds"),
        priority=_integer(values, "priority"),
        poll_interval_minutes=_integer(values, "poll_interval_minutes"),
        daily_window_start=values.get("daily_window_start", ""),
        daily_window_end=values.get("daily_window_end", ""),
        # RSS ingestion processes the bounded feed response; this legacy RPA
        # limit is no longer user-configurable but remains in the persistence API.
        max_articles_per_round=5,
        collect_today_only=_checked(values, "collect_today_only"),
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


def _article_defaults() -> dict[str, object]:
    return {
        "account_name": "",
        "account_type": "subscription",
        "feed_url": "",
        "request_timeout_seconds": 30,
        "priority": 10,
        "poll_interval_minutes": 10,
        "daily_window_start": "00:00",
        "daily_window_end": "23:59",
        "collect_today_only": True,
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


def _article_values(source) -> dict[str, object]:
    return {
        "account_name": source.account_name,
        "account_type": source.account_type,
        "feed_url": source.feed_url or "",
        "request_timeout_seconds": source.request_timeout_seconds,
        "priority": source.priority,
        "poll_interval_minutes": source.poll_interval_minutes,
        "daily_window_start": source.daily_window_start,
        "daily_window_end": source.daily_window_end,
        "collect_today_only": source.collect_today_only,
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


def _article_form_response(
    request: Request,
    values: dict[str, object],
    error: str | None,
    source_id: int | None = None,
    *,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="sources/article_form.html",
        context={
            "section": "articles",
            "values": values,
            "error": error,
            "source_id": source_id,
        },
        status_code=status_code,
    )


def _article_validation_message(values: dict[str, str]) -> str:
    try:
        if int(values.get("poll_interval_minutes", "")) < 10:
            return "公众号采集间隔不能少于 10 分钟。"
    except ValueError:
        pass
    return "请检查表单字段，公众号间隔至少 10 分钟。"


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
