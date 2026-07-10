from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.security.markdown import render_safe_markdown


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()
REPORT_TYPES = frozenset({"group", "article", "summary"})


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request) -> Response:
    try:
        values = _query_values(request)
        report_date = _report_date(request, values)
        report_type = values.get("type", "group")
        if report_type not in REPORT_TYPES:
            raise ValueError("invalid report type")
        source = _optional(values, "source")
        page, page_size = _pagination(values)
        offset = (page - 1) * page_size
        context = await _load_report_context(
            request,
            report_type,
            report_date,
            source,
            page_size,
            offset,
        )
    except (TypeError, ValueError):
        return _error_response(request)
    return templates.TemplateResponse(
        request=request,
        name="reports/index.html",
        context={
            "section": "reports",
            "values": values,
            "report_date": report_date,
            "report_type": report_type,
            "source": source,
            "page": page,
            "page_size": page_size,
            "previous_url": _page_url(values, report_date, report_type, page - 1)
            if page > 1
            else None,
            **context,
        },
    )


async def _load_report_context(
    request: Request,
    report_type: str,
    report_date: date,
    source: str | None,
    page_size: int,
    offset: int,
) -> dict[str, object]:
    if report_type == "summary":
        bundle = await run_in_threadpool(
            request.app.state.summary_report_service.load_sources,
            report_date,
            page_size + 1,
            offset,
        )
        has_next = (
            len(bundle.group_reports) > page_size
            or len(bundle.article_reports) > page_size
        )
        return {
            "group_reports": bundle.group_reports[:page_size],
            "article_reports": bundle.article_reports[:page_size],
            "reports": (),
            "detail": None,
            "safe_markdown": None,
            "next_url": _next_url(has_next, report_date, report_type, source, page_size, offset),
        }

    service = (
        request.app.state.group_report_service
        if report_type == "group"
        else request.app.state.article_report_service
    )
    reports = await run_in_threadpool(
        service.list_reports,
        report_date,
        source,
        page_size + 1,
        offset,
    )
    has_next = len(reports) > page_size
    detail = None
    safe_markdown = None
    if source is not None:
        detail = await run_in_threadpool(service.get_report, report_date, source)
        if detail is not None:
            safe_markdown = render_safe_markdown(detail.markdown_body)
    return {
        "reports": reports[:page_size],
        "group_reports": (),
        "article_reports": (),
        "detail": detail,
        "safe_markdown": safe_markdown,
        "next_url": _next_url(has_next, report_date, report_type, source, page_size, offset),
    }


def _next_url(
    has_next: bool,
    report_date: date,
    report_type: str,
    source: str | None,
    page_size: int,
    offset: int,
) -> str | None:
    if not has_next:
        return None
    page = offset // page_size + 2
    values = {
        "date": report_date.isoformat(),
        "type": report_type,
        "page": str(page),
        "page_size": str(page_size),
    }
    if source is not None:
        values["source"] = source
    return f"/reports?{urlencode(values)}"


def _page_url(
    values: dict[str, str], report_date: date, report_type: str, page: int
) -> str:
    query = {
        **values,
        "date": report_date.isoformat(),
        "type": report_type,
        "page": str(page),
    }
    query.setdefault("page_size", "20")
    return f"/reports?{urlencode(query)}"


def _query_values(request: Request) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in request.query_params:
        items = request.query_params.getlist(key)
        if len(items) != 1:
            raise ValueError("duplicate query parameter")
        values[key] = items[0]
    return values


def _report_date(request: Request, values: dict[str, str]) -> date:
    value = values.get("date")
    if value is None:
        timezone_name = request.app.state.config.app.timezone
        return datetime.now(ZoneInfo(timezone_name)).date()
    return date.fromisoformat(value)


def _pagination(values: dict[str, str]) -> tuple[int, int]:
    page = _positive_integer(values.get("page", "1"))
    page_size = _positive_integer(values.get("page_size", "20"))
    if page_size > 100:
        raise ValueError("page_size must not exceed 100")
    return page, page_size


def _positive_integer(value: str) -> int:
    if not value or value.strip() != value:
        raise ValueError("invalid integer")
    parsed = int(value)
    if parsed < 1:
        raise ValueError("invalid integer")
    return parsed


def _optional(values: dict[str, str], field: str) -> str | None:
    value = values.get(field)
    if value is None or value == "":
        return None
    if value.strip() != value or len(value) > 200:
        raise ValueError(f"invalid {field}")
    return value


def _error_response(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="reports/error.html",
        context={"section": "reports"},
        status_code=422,
    )
