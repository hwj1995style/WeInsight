from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.domain.admin_results import (
    ArticleDetailFilter,
    GroupDetailFilter,
)
from app.web.pagination import build_pagination


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="/results")


@router.get("/groups", response_class=HTMLResponse)
async def group_results(request: Request) -> Response:
    try:
        values = _query_values(request)
        page, page_size = _pagination(values)
        filters = GroupDetailFilter(
            group_name=_optional(values, "group_name"),
            start_at=_optional_datetime(values, "start_at"),
            end_at=_optional_datetime(values, "end_at"),
            intent_type=_optional(values, "intent_type"),
        )
        if (
            filters.start_at is not None
            and filters.end_at is not None
            and filters.start_at >= filters.end_at
        ):
            raise ValueError("invalid time range")
        result = await run_in_threadpool(
            request.app.state.result_service.list_group_details,
            filters,
            page,
            page_size,
        )
    except (TypeError, ValueError):
        return _error_response(request, "/results/groups")
    return _results_response(
        request,
        "results/groups.html",
        result,
        values,
        groups=result.items,
    )


@router.get("/articles", response_class=HTMLResponse)
async def article_results(request: Request) -> Response:
    try:
        values = _query_values(request)
        page, page_size = _pagination(values)
        filters = ArticleDetailFilter(
            account_name=_optional(values, "account_name"),
            publish_date=_optional_date(values, "publish_date"),
            quote_date=_optional_date(values, "quote_date"),
        )
        result = await run_in_threadpool(
            request.app.state.result_service.list_article_details,
            filters,
            page,
            page_size,
        )
    except (TypeError, ValueError):
        return _error_response(request, "/results/articles")
    return _results_response(
        request,
        "results/articles.html",
        result,
        values,
        articles=result.items,
    )


@router.get("/prices", response_class=HTMLResponse)
async def price_results(request: Request) -> Response:
    try:
        values = _query_values(request)
        if values.keys() - {"quote_date"}:
            raise ValueError("unsupported query parameter")
        requested_date = _optional_date(values, "quote_date")
        matrix = await run_in_threadpool(
            request.app.state.result_service.get_price_matrix,
            requested_date,
        )
    except (TypeError, ValueError):
        return _error_response(request, "/results/prices")
    return templates.TemplateResponse(
        request=request,
        name="results/prices.html",
        context={
            "section": "results",
            "matrix": matrix,
            "quote_date": matrix.quote_date if matrix is not None else requested_date,
        },
    )


def _query_values(request: Request) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in request.query_params:
        items = request.query_params.getlist(key)
        if len(items) != 1:
            raise ValueError("duplicate query parameter")
        values[key] = items[0]
    return values


def _pagination(values: dict[str, str]) -> tuple[int, int]:
    page = _positive_integer(values.get("page", "1"), "page")
    page_size = _positive_integer(values.get("page_size", "20"), "page_size")
    if page_size > 100:
        raise ValueError("page_size must not exceed 100")
    return page, page_size


def _positive_integer(value: str, field: str) -> int:
    if not value or value.strip() != value:
        raise ValueError(f"invalid {field}")
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"invalid {field}")
    return parsed


def _optional(values: dict[str, str], field: str) -> str | None:
    value = values.get(field)
    if value is None or value == "":
        return None
    if value.strip() != value:
        raise ValueError(f"invalid {field}")
    return value


def _optional_date(values: dict[str, str], field: str) -> date | None:
    value = _optional(values, field)
    return None if value is None else date.fromisoformat(value)


def _optional_datetime(values: dict[str, str], field: str) -> datetime | None:
    value = _optional(values, field)
    return None if value is None else datetime.fromisoformat(value)


def _results_response(
    request: Request,
    template_name: str,
    result,
    values: dict[str, str],
    **context,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "section": "results",
            "values": values,
            "page": result,
            "pagination": build_pagination(
                request.url.path, values, page=result.page,
                page_size=result.page_size, total_count=result.total_count,
            ),
            "pagination_label": "结果分页",
            **context,
        },
    )


def _page_url(path: str, values: dict[str, str], page: int) -> str:
    query = {**values, "page": str(page)}
    query.setdefault("page_size", "20")
    return f"{path}?{urlencode(query)}"


def _error_response(request: Request, return_url: str) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="results/error.html",
        context={
            "section": "results",
            "message": "查询条件无效，请检查日期、筛选条件和分页范围。",
            "return_url": return_url,
        },
        status_code=422,
    )
