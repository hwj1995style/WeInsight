from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.security.markdown import render_safe_markdown
from app.services.report_generation_service import ReportValidationError
from app.storage.report_request_repo import (
    ReportRequestConflictError,
    ReportRequestStatus,
    ReportType,
)
from app.domain.report_lifecycle import GenerationTrigger, ReportStatus


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()
REPORT_TYPES = frozenset({"group", "article", "summary"})
_SOURCE_OPTION_LIMIT = 1000
_LIST_QUERY_FIELDS = frozenset({"date", "type", "source", "page", "page_size"})
_GENERATE_FORM_FIELDS = frozenset(
    {"csrf_token", "idempotency_key", "report_type", "report_date", "source_name"}
)
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")
_IDEMPOTENCY_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,100}")
_POLLING_STATUSES = frozenset(
    {ReportRequestStatus.PENDING, ReportRequestStatus.RUNNING}
)
_REQUEST_STATUS_LABELS = {
    ReportRequestStatus.PENDING: "等待处理",
    ReportRequestStatus.RUNNING: "生成中",
    ReportRequestStatus.SUCCESS: "生成成功",
    ReportRequestStatus.PARTIAL_SUCCESS: "部分成功",
    ReportRequestStatus.FAILED: "生成失败",
}
_REQUEST_TYPE_LABELS = {
    ReportType.GROUP: "微信群",
    ReportType.ARTICLE: "公众号",
    ReportType.SUMMARY: "汇总",
    ReportType.ALL: "全部日报",
}
_LIFECYCLE_LABELS = {
    ReportStatus.PROVISIONAL: "临时版",
    ReportStatus.FINAL: "最终版",
}
_TRIGGER_LABELS = {
    GenerationTrigger.MANUAL: "手动生成",
    GenerationTrigger.AUTOMATIC: "自动生成",
    GenerationTrigger.COMPENSATION: "次日补偿",
    GenerationTrigger.LEGACY: "历史数据",
}


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
            "source_options": (),
            "next_url": _next_url(has_next, report_date, report_type, source, page_size, offset),
            "idempotency_key": secrets.token_urlsafe(32),
            "lifecycle_labels": _LIFECYCLE_LABELS,
            "trigger_labels": _TRIGGER_LABELS,
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
    source_reports = await run_in_threadpool(
        service.list_reports,
        report_date,
        None,
        _SOURCE_OPTION_LIMIT,
        0,
    )
    source_field = "group_name" if report_type == "group" else "account_name"
    source_options = tuple(
        sorted({str(getattr(item, source_field)) for item in source_reports})
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
        "source_options": source_options,
        "next_url": _next_url(
            has_next,
            report_date,
            report_type,
            source,
            page_size,
            offset,
        ),
        "idempotency_key": secrets.token_urlsafe(32),
        "lifecycle_labels": _LIFECYCLE_LABELS,
        "trigger_labels": _TRIGGER_LABELS,
    }


@router.post("/reports/generate", response_class=HTMLResponse)
async def generate_report(request: Request) -> Response:
    try:
        values = await _strict_form_values(request, _GENERATE_FORM_FIELDS)
        if not secrets.compare_digest(
            values["csrf_token"],
            str(request.state.csrf_token or ""),
        ):
            raise ValueError("invalid csrf token")
        idempotency_key = values["idempotency_key"]
        if _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key) is None:
            raise ValueError("invalid idempotency key")
        report_type = ReportType(values["report_type"])
        report_date = _strict_date(values["report_date"])
        source_name = _optional_source(values["source_name"])
        if report_type in {ReportType.SUMMARY, ReportType.ALL}:
            if source_name is not None:
                raise ValueError("source is not allowed")
        request_id = await run_in_threadpool(
            request.app.state.report_request_service.request_manual,
            report_type,
            report_date,
            source_name,
            request.state.admin.username,
            idempotency_key,
            _now(request),
        )
    except ReportRequestConflictError:
        return _error_response(
            request,
            title="日报生成请求冲突",
            message="该表单已用于不同请求，请刷新页面后重试。",
            status_code=409,
        )
    except (KeyError, TypeError, ValueError, ReportValidationError):
        return _error_response(
            request,
            title="日报生成请求无效",
            message="请检查日报类型、日期和采集对象后重试。",
            status_code=422,
        )
    except Exception:
        return _service_unavailable(request)
    return RedirectResponse(
        f"/reports/requests/{int(request_id)}",
        status_code=303,
    )


@router.get("/reports/requests/{request_id}", response_class=HTMLResponse)
async def report_request_status(request: Request, request_id: str) -> Response:
    try:
        parsed_id = _positive_integer(request_id)
        item = await run_in_threadpool(
            request.app.state.report_request_repo.get_request,
            parsed_id,
        )
    except (TypeError, ValueError):
        item = None
    except Exception:
        return _service_unavailable(request)
    if item is None:
        return _error_response(
            request,
            title="日报请求不存在",
            message="该日报生成请求不存在或已被清理。",
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="reports/request_status.html",
        context={
            "section": "reports",
            "item": item,
            "polling": item.status in _POLLING_STATUSES,
            "status_label": _REQUEST_STATUS_LABELS[item.status],
            "type_label": _REQUEST_TYPE_LABELS[item.report_type],
        },
    )


@router.get("/reports/group/{report_date}/{source_name}.md")
async def download_group_report(
    request: Request,
    report_date: str,
    source_name: str,
) -> Response:
    try:
        selected_date = _strict_date(report_date)
        selected_source = _required_source(source_name)
        item = await run_in_threadpool(
            request.app.state.group_report_service.get_report,
            selected_date,
            selected_source,
        )
    except (TypeError, ValueError):
        item = None
    except Exception:
        return _service_unavailable(request)
    if item is None:
        return _download_not_found(request)
    return _markdown_download(
        item.markdown_body,
        f"weinsight-group-report-{selected_date.isoformat()}.md",
    )


@router.get("/reports/article/{report_date}/{source_name}.md")
async def download_article_report(
    request: Request,
    report_date: str,
    source_name: str,
) -> Response:
    try:
        selected_date = _strict_date(report_date)
        selected_source = _required_source(source_name)
        item = await run_in_threadpool(
            request.app.state.article_report_service.get_report,
            selected_date,
            selected_source,
        )
    except (TypeError, ValueError):
        item = None
    except Exception:
        return _service_unavailable(request)
    if item is None:
        return _download_not_found(request)
    return _markdown_download(
        item.markdown_body,
        f"weinsight-article-report-{selected_date.isoformat()}.md",
    )


@router.get("/reports/summary/{report_date}.md")
async def download_summary_report(request: Request, report_date: str) -> Response:
    try:
        selected_date = _strict_date(report_date)
        bundle = await run_in_threadpool(
            request.app.state.summary_report_service.load_sources,
            selected_date,
        )
    except (TypeError, ValueError):
        bundle = None
    except Exception:
        return _service_unavailable(request)
    if bundle is None or not (bundle.group_reports or bundle.article_reports):
        return _download_not_found(request)
    return _markdown_download(
        _summary_markdown(bundle),
        f"weinsight-summary-report-{selected_date.isoformat()}.md",
    )


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
        if key not in _LIST_QUERY_FIELDS:
            raise ValueError("unknown query parameter")
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
    if (
        not isinstance(value, str)
        or _POSITIVE_INTEGER_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("invalid integer")
    return int(value)


def _optional(values: dict[str, str], field: str) -> str | None:
    value = values.get(field)
    if value is None or value == "":
        return None
    return _required_source(value)


async def _strict_form_values(
    request: Request,
    allowed: frozenset[str],
) -> dict[str, str]:
    form = await request.form()
    collected: dict[str, list[str]] = {}
    for key, value in form.multi_items():
        if key not in allowed or not isinstance(value, str):
            raise ValueError("unknown form field")
        collected.setdefault(key, []).append(value)
    if set(collected) != set(allowed):
        raise ValueError("missing form field")
    if any(len(values) != 1 for values in collected.values()):
        raise ValueError("duplicate form field")
    return {key: values[0] for key, values in collected.items()}


def _strict_date(value: str) -> date:
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid date")
    return date.fromisoformat(value)


def _optional_source(value: str) -> str | None:
    return None if value == "" else _required_source(value)


def _required_source(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or value in {".", ".."}
        or any(character in value for character in ("/", "\\", "\r", "\n"))
        or any(
            unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError("invalid source")
    return value


def _markdown_download(body: str, filename: str) -> Response:
    if not isinstance(body, str):
        raise TypeError("markdown body must be a string")
    return Response(
        content=body.encode("utf-8"),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _summary_markdown(bundle) -> str:
    lines = [f"# 双链路汇总日报（{bundle.report_date.isoformat()}）", ""]
    lines.extend(
        [
            "## 微信群日报摘要",
            "",
            "| 对象 | 标题 | 消息 | 发送人 | 需求 | 供应 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in bundle.group_reports:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(row.group_name),
                    _markdown_cell(row.title),
                    str(int(row.message_count)),
                    str(int(row.sender_count)),
                    str(int(row.demand_count)),
                    str(int(row.supply_count)),
                )
            )
            + " |"
        )
    if not bundle.group_reports:
        lines.append("| 暂无 | 暂无 | 0 | 0 | 0 | 0 |")
    lines.extend(
        [
            "",
            "## 公众号日报摘要",
            "",
            "| 对象 | 标题 | 文章 | 平均长度 |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for row in bundle.article_reports:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(row.account_name),
                    _markdown_cell(row.title),
                    str(int(row.article_count)),
                    str(int(row.avg_content_length)),
                )
            )
            + " |"
        )
    if not bundle.article_reports:
        lines.append("| 暂无 | 暂无 | 0 | 0 |")
    return "\n".join(lines) + "\n"


def _markdown_cell(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("<", "＜")
        .replace(">", "＞")[:200]
    )


def _download_not_found(request: Request) -> Response:
    return _error_response(
        request,
        title="日报不存在",
        message="该日期和对象没有可下载的日报。",
        status_code=404,
    )


def _service_unavailable(request: Request) -> Response:
    return _error_response(
        request,
        title="日报服务暂不可用",
        message="请稍后重试。",
        status_code=503,
    )


def _now(request: Request) -> datetime:
    timezone_name = request.app.state.config.app.timezone
    return datetime.now(ZoneInfo(timezone_name))


def _error_response(
    request: Request,
    *,
    title: str = "日报查询条件无效",
    message: str = "请检查日期、日报类型、采集对象与分页范围。",
    status_code: int = 422,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="reports/error.html",
        context={
            "section": "reports",
            "error_title": title,
            "error_message": message,
        },
        status_code=status_code,
    )
