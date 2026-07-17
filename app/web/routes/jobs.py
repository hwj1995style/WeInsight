from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import JobStatus, PipelineType
from app.services.collection_job_service import (
    CollectionJobDetail,
    CreateCollectionJobCommand,
    UpdateCollectionJobCommand,
    JobListFilter,
    JobMixedPipelineError,
    ManagedJobMutationError,
    JobNotFoundError,
    JobOverlapError,
    JobScheduleExpiredError,
    JobStateTransitionError,
    JobTargetDisabledError,
    JobTargetNotFoundError,
    JobValidationError,
    JobVersionConflictError,
)
from app.services.runtime_monitor_service import JobRuntimeHistory
from app.web.pagination import build_pagination


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="/jobs")

_LIST_QUERY_FIELDS = frozenset(
    {"pipeline", "status", "date", "name", "page", "page_size"}
)
_NEW_QUERY_FIELDS = frozenset({"pipeline"})
_CREATE_COMMON_FIELDS = frozenset(
    {
        "csrf_token",
        "job_name",
        "pipeline_type",
        "target_ids",
        "effective_start_at",
        "effective_end_at",
        "daily_window_start",
        "daily_window_end",
    }
)
_ACTION_FIELDS = frozenset({"csrf_token", "version"})
_ACTION_OPTIONAL_FIELDS = frozenset({"return_to"})
_EDIT_EXTRA_FIELDS = frozenset({"version"})
_DATETIME_LOCAL_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_TIME_PATTERN = re.compile(r"[0-9]{2}:[0-9]{2}")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")

PIPELINE_LABELS = {
    PipelineType.GROUP: "微信群",
    PipelineType.ARTICLE: "公众号",
}
STATUS_LABELS = {
    JobStatus.SCHEDULED: "待开始",
    JobStatus.ACTIVE: "运行中",
    JobStatus.STOP_REQUESTED: "停止中",
    JobStatus.STOPPED: "已停止",
    JobStatus.COMPLETED: "已完成",
    JobStatus.DELETED: "已删除",
}


@router.get("", response_class=HTMLResponse)
async def job_list(request: Request) -> Response:
    try:
        values = _single_query_values(request, _LIST_QUERY_FIELDS)
        filters = JobListFilter(
            pipeline_type=_optional_pipeline(values.get("pipeline")),
            status=_optional_status(values.get("status")),
            name_contains=_optional_name(values.get("name")),
            date=_optional_date(values.get("date")),
        )
        page = _positive_integer(values.get("page", "1"), "page")
        page_size = _positive_integer(values.get("page_size", "20"), "page_size")
        if page_size > 100:
            raise ValueError("page_size must be at most 100")
        result = await run_in_threadpool(
            request.app.state.job_service.list_jobs,
            filters,
            page,
            page_size,
        )
    except (ValueError, JobValidationError):
        return _job_list_response(
            request,
            PagedResult([], 1, 20, 0),
            values={
                "pipeline": "",
                "status": "",
                "date": "",
                "name": "",
                "page_size": "20",
            },
            error="请检查筛选条件后重试。",
            status_code=422,
        )
    normalized_values = {
        "pipeline": values.get("pipeline", ""),
        "status": values.get("status", ""),
        "date": values.get("date", ""),
        "name": values.get("name", ""),
        "page_size": str(page_size),
    }
    return _job_list_response(request, result, normalized_values)


@router.get("/new", response_class=HTMLResponse)
async def job_new(request: Request) -> Response:
    try:
        values = _single_query_values(request, _NEW_QUERY_FIELDS)
        pipeline = _required_pipeline(values.get("pipeline", "group"))
    except ValueError:
        return _job_form_response(
            request,
            PipelineType.GROUP,
            (),
            _job_form_defaults(PipelineType.GROUP),
            "请检查任务链路后重试。",
            status_code=422,
        )
    if pipeline is PipelineType.ARTICLE:
        return RedirectResponse("/jobs", status_code=303)
    try:
        targets = await _load_enabled_targets(request, pipeline)
    except ValueError:
        return _job_form_response(
            request,
            pipeline,
            (),
            _job_form_defaults(pipeline),
            "无法加载已启用名单，请稍后重试。",
            status_code=422,
        )
    return _job_form_response(
        request,
        pipeline,
        targets,
        _job_form_defaults(pipeline, targets),
        None,
    )


@router.post("", response_class=HTMLResponse)
async def job_create(request: Request) -> Response:
    try:
        values, pipeline = await _parse_create_form(request)
    except ValueError as exc:
        pipeline, values = await _create_form_echo(request)
        targets = await _safe_load_enabled_targets(request, pipeline)
        return _job_form_response(
            request,
            pipeline,
            targets,
            values,
            _form_validation_message(exc),
            status_code=422,
        )

    if pipeline is PipelineType.ARTICLE:
        return _job_form_response(
            request,
            pipeline,
            (),
            values,
            "公众号采集任务由系统统一管理，不能人工创建。",
            status_code=422,
        )

    try:
        command = _create_command(request, values, pipeline)
    except ValueError as exc:
        return await _create_error_response(
            request,
            pipeline,
            values,
            _form_validation_message(exc),
            status_code=422,
        )

    try:
        job_id = await run_in_threadpool(
            request.app.state.job_service.create_job,
            command,
            request.state.admin.username,
            _now(request.app.state.config.app.timezone),
        )
    except JobOverlapError as exc:
        return await _create_error_response(
            request,
            pipeline,
            values,
            "所选名单与现有任务的运行时间重叠。",
            status_code=409,
            job_names=exc.job_names,
        )
    except JobTargetNotFoundError:
        return await _create_error_response(
            request,
            pipeline,
            values,
            "所选名单已不存在，请刷新后重新选择。",
            status_code=409,
        )
    except JobTargetDisabledError:
        return await _create_error_response(
            request,
            pipeline,
            values,
            "所选名单已停用，请刷新后重新选择。",
            status_code=409,
        )
    except JobMixedPipelineError:
        return await _create_error_response(
            request,
            pipeline,
            values,
            "所有目标必须属于同一采集链路。",
            status_code=422,
        )
    except JobValidationError as exc:
        return await _create_error_response(
            request,
            pipeline,
            values,
            _job_validation_message(exc, pipeline),
            status_code=422,
        )
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int) -> Response:
    try:
        job = await run_in_threadpool(
            request.app.state.job_service.get_job,
            job_id,
        )
    except (JobNotFoundError, JobValidationError):
        return _job_detail_response(
            request,
            None,
            "采集任务不存在或已被删除。",
            status_code=404,
        )
    history = await _load_job_history(request, job_id)
    return _job_detail_response(request, job, history=history)


@router.get("/{job_id}/edit", response_class=HTMLResponse)
async def job_edit(request: Request, job_id: int) -> Response:
    try:
        job = await run_in_threadpool(
            request.app.state.job_service.get_job,
            job_id,
        )
    except (JobNotFoundError, JobValidationError):
        return _job_detail_response(
            request,
            None,
            "采集任务不存在或已被删除。",
            status_code=404,
        )
    if job.managed_key == "article_global":
        return _job_detail_response(
            request,
            job,
            "系统管理任务不允许人工编辑。",
            status_code=403,
        )
    if job.status is not JobStatus.STOPPED:
        return _job_detail_response(
            request,
            job,
            "只有已停止任务可以编辑。",
            status_code=409,
        )
    try:
        targets = await _load_enabled_targets(request, job.pipeline_type)
    except ValueError:
        targets = ()
    return _job_form_response(
        request,
        job.pipeline_type,
        targets,
        _job_edit_values(job),
        None,
        mode="edit",
        job_id=job.id,
        version=str(job.version),
    )


@router.post("/{job_id}/edit", response_class=HTMLResponse)
async def job_update(request: Request, job_id: int) -> Response:
    try:
        values, pipeline, version = await _parse_edit_form(request)
        command = _update_command(request, values, pipeline)
    except ValueError as exc:
        pipeline, values = await _create_form_echo(request)
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            _form_validation_message(exc),
            status_code=422,
        )
    service = request.app.state.job_service
    try:
        await run_in_threadpool(
            service.update_job,
            job_id,
            command,
            version,
            request.state.admin.username,
            _now(request.app.state.config.app.timezone),
        )
    except JobOverlapError as exc:
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            "所选名单与现有任务的运行时间重叠。",
            status_code=409,
            job_names=exc.job_names,
        )
    except JobTargetNotFoundError:
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            "所选名单已不存在，请刷新后重新选择。",
            status_code=409,
        )
    except JobTargetDisabledError:
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            "所选名单已停用，请刷新后重新选择。",
            status_code=409,
        )
    except JobMixedPipelineError:
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            "任务采集链路不允许修改。",
            status_code=422,
        )
    except JobValidationError as exc:
        return await _update_error_response(
            request,
            job_id,
            pipeline,
            values,
            _job_validation_message(exc, pipeline),
            status_code=422,
        )
    except JobNotFoundError:
        return _job_detail_response(
            request,
            None,
            "采集任务不存在或已被删除。",
            status_code=404,
        )
    except (JobVersionConflictError, JobStateTransitionError) as exc:
        try:
            current = await run_in_threadpool(service.get_job, job_id)
        except JobNotFoundError:
            current = None
        message = (
            "任务状态已更新，请根据当前状态重新操作。"
            if isinstance(exc, JobVersionConflictError)
            else "只有已停止任务可以编辑，页面已刷新。"
        )
        return _job_detail_response(
            request,
            current,
            message,
            status_code=409,
        )
    except ManagedJobMutationError:
        try:
            current = await run_in_threadpool(service.get_job, job_id)
        except JobNotFoundError:
            current = None
        return _job_detail_response(
            request,
            current,
            "系统管理任务不允许人工编辑。",
            status_code=403,
        )
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/{job_id}/stop", response_class=HTMLResponse)
async def job_stop(request: Request, job_id: int) -> Response:
    return await _job_action(request, job_id, "stop")


@router.post("/{job_id}/start", response_class=HTMLResponse)
async def job_start(request: Request, job_id: int) -> Response:
    return await _job_action(request, job_id, "start")


@router.post("/{job_id}/delete", response_class=HTMLResponse)
async def job_delete(request: Request, job_id: int) -> Response:
    return await _job_action(request, job_id, "delete")


async def _job_action(request: Request, job_id: int, action: str) -> Response:
    try:
        values = await _strict_form_values(
            request,
            allowed=_ACTION_FIELDS | _ACTION_OPTIONAL_FIELDS,
            repeated=frozenset(),
            optional=_ACTION_OPTIONAL_FIELDS,
        )
        version = _positive_integer(values["version"], "version")
        return_to = values.get("return_to")
        if return_to not in {None, "list"}:
            raise ValueError("invalid return target")
    except (KeyError, ValueError):
        return _job_detail_response(
            request,
            None,
            "请检查操作参数后重试。",
            status_code=422,
        )

    service = request.app.state.job_service
    try:
        if action == "start":
            await run_in_threadpool(
                service.start_job,
                job_id,
                version,
                request.state.admin.username,
                _now(request.app.state.config.app.timezone),
            )
        elif action == "stop":
            await run_in_threadpool(
                service.request_stop,
                job_id,
                version,
                request.state.admin.username,
                _now(request.app.state.config.app.timezone),
            )
        else:
            await run_in_threadpool(
                service.delete_job,
                job_id,
                version,
                request.state.admin.username,
                _now(request.app.state.config.app.timezone),
            )
    except JobNotFoundError:
        return _job_detail_response(
            request,
            None,
            "采集任务不存在或已被删除。",
            status_code=404,
        )
    except (JobVersionConflictError, JobStateTransitionError) as exc:
        try:
            current = await run_in_threadpool(service.get_job, job_id)
        except JobNotFoundError:
            return _job_detail_response(
                request,
                None,
                "采集任务不存在或已被删除。",
                status_code=404,
            )
        message = (
            "任务状态已更新，请根据当前状态重新操作。"
            if isinstance(exc, JobVersionConflictError)
            else "当前状态不允许此操作，页面已刷新。"
        )
        return _job_detail_response(
            request,
            current,
            message,
            status_code=409,
        )
    except JobScheduleExpiredError:
        try:
            current = await run_in_threadpool(service.get_job, job_id)
        except JobNotFoundError:
            current = None
        return _job_detail_response(
            request,
            current,
            "任务有效期已结束，无法重新启动。",
            status_code=409,
        )
    except ManagedJobMutationError:
        try:
            current = await run_in_threadpool(service.get_job, job_id)
        except JobNotFoundError:
            current = None
        return _job_detail_response(
            request,
            current,
            "系统管理任务不允许人工启动、停止或删除。",
            status_code=403,
        )
    except JobValidationError:
        return _job_detail_response(
            request,
            None,
            "请检查操作参数后重试。",
            status_code=422,
        )

    if action == "delete" or return_to == "list":
        return RedirectResponse("/jobs", status_code=303)
    try:
        current = await run_in_threadpool(service.get_job, job_id)
    except JobNotFoundError:
        return _job_detail_response(
            request,
            None,
            "采集任务不存在或已被删除。",
            status_code=404,
        )
    history = await _load_job_history(request, job_id)
    return _job_detail_response(request, current, history=history)


async def _load_job_history(request: Request, job_id: int) -> JobRuntimeHistory:
    try:
        return await run_in_threadpool(
            request.app.state.runtime_monitor_service.get_job_history,
            job_id,
            10,
        )
    except Exception:
        return JobRuntimeHistory((), ())


def _job_list_response(
    request: Request,
    page: PagedResult,
    values: dict[str, str],
    error: str | None = None,
    *,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="jobs/index.html",
        context={
            "section": "jobs",
            "jobs": page.items,
            "page": page,
            "values": values,
            "pipeline_labels": PIPELINE_LABELS,
            "status_labels": STATUS_LABELS,
            "pagination": build_pagination(
                "/jobs", values, page=page.page,
                page_size=page.page_size, total_count=page.total_count,
            ),
            "pagination_label": "采集任务分页",
            "error": error,
        },
        status_code=status_code,
    )


def _job_form_response(
    request: Request,
    pipeline: PipelineType,
    targets,
    values: dict[str, object],
    error: str | None,
    *,
    status_code: int = 200,
    job_names: tuple[str, ...] = (),
    mode: str = "create",
    job_id: int | None = None,
    version: str = "",
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="jobs/form.html",
        context={
            "section": "jobs",
            "pipeline": pipeline,
            "targets": targets,
            "values": values,
            "error": error,
            "job_names": job_names,
            "mode": mode,
            "job_id": job_id,
            "version": version,
        },
        status_code=status_code,
    )


def _job_detail_response(
    request: Request,
    job: CollectionJobDetail | None,
    error: str | None = None,
    *,
    status_code: int = 200,
    history: JobRuntimeHistory | None = None,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="jobs/detail.html",
        context={
            "section": "jobs",
            "job": job,
            "error": error,
            "pipeline_labels": PIPELINE_LABELS,
            "status_labels": STATUS_LABELS,
            "history": history or JobRuntimeHistory((), ()),
        },
        status_code=status_code,
    )


async def _create_error_response(
    request: Request,
    pipeline: PipelineType,
    values: dict[str, object],
    message: str,
    *,
    status_code: int,
    job_names: tuple[str, ...] = (),
) -> Response:
    targets = await _safe_load_enabled_targets(request, pipeline)
    return _job_form_response(
        request,
        pipeline,
        targets,
        values,
        message,
        status_code=status_code,
        job_names=job_names,
    )


async def _update_error_response(
    request: Request,
    job_id: int,
    pipeline: PipelineType,
    values: dict[str, object],
    message: str,
    *,
    status_code: int,
    job_names: tuple[str, ...] = (),
) -> Response:
    targets = await _safe_load_enabled_targets(request, pipeline)
    return _job_form_response(
        request,
        pipeline,
        targets,
        values,
        message,
        status_code=status_code,
        job_names=job_names,
        mode="edit",
        job_id=job_id,
        version=str(values.get("version", "")),
    )


async def _load_enabled_targets(request: Request, pipeline: PipelineType):
    service = request.app.state.source_service
    if pipeline is PipelineType.GROUP:
        return await run_in_threadpool(service.list_enabled_groups_for_job, 100)
    return await run_in_threadpool(service.list_enabled_articles_for_job, 100)


async def _safe_load_enabled_targets(request: Request, pipeline: PipelineType):
    try:
        return await _load_enabled_targets(request, pipeline)
    except ValueError:
        return ()


def _job_form_defaults(pipeline: PipelineType, targets=()) -> dict[str, object]:
    interval = 30 if pipeline is PipelineType.GROUP else 10
    if targets:
        first = targets[0]
        interval = (
            first.poll_interval_seconds
            if pipeline is PipelineType.GROUP
            else first.poll_interval_minutes
        )
    return {
        "job_name": "",
        "pipeline_type": pipeline.value,
        "target_ids": (),
        "effective_start_at": "",
        "effective_end_at": "",
        "daily_window_start": "00:00",
        "daily_window_end": "00:00",
        "interval_value": interval,
    }


def _job_edit_values(job: CollectionJobDetail) -> dict[str, object]:
    interval = (
        job.schedule.interval_seconds
        if job.pipeline_type is PipelineType.GROUP
        else job.schedule.interval_seconds // 60
    )
    return {
        "job_name": job.job_name,
        "pipeline_type": job.pipeline_type.value,
        "target_ids": tuple(str(value) for value in job.target_ids),
        "effective_start_at": job.schedule.effective_start_at.strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "effective_end_at": job.schedule.effective_end_at.strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "daily_window_start": job.schedule.daily_window_start.strftime("%H:%M"),
        "daily_window_end": job.schedule.daily_window_end.strftime("%H:%M"),
        "interval_value": interval,
        "version": str(job.version),
    }


async def _parse_create_form(
    request: Request,
) -> tuple[dict[str, object], PipelineType]:
    values, pipeline, _ = await _parse_job_form(request, frozenset())
    return values, pipeline


async def _parse_edit_form(
    request: Request,
) -> tuple[dict[str, object], PipelineType, int]:
    values, pipeline, parsed = await _parse_job_form(
        request, _EDIT_EXTRA_FIELDS
    )
    version_value = parsed["version"]
    if not isinstance(version_value, str):
        raise ValueError("invalid version")
    version = _positive_integer(version_value, "version")
    values["version"] = version_value
    return values, pipeline, version


async def _parse_job_form(
    request: Request,
    extra_fields: frozenset[str],
) -> tuple[
    dict[str, object],
    PipelineType,
    dict[str, str | tuple[str, ...]],
]:
    form = await request.form()
    pipeline_values = [
        value
        for key, value in form.multi_items()
        if key == "pipeline_type" and isinstance(value, str)
    ]
    if len(pipeline_values) != 1:
        raise ValueError("duplicate form field")
    pipeline = _required_pipeline(pipeline_values[0])
    interval_field = (
        "interval_seconds"
        if pipeline is PipelineType.GROUP
        else "interval_minutes"
    )
    parsed = await _strict_form_values(
        request,
        allowed=_CREATE_COMMON_FIELDS | {interval_field} | extra_fields,
        repeated=frozenset({"target_ids"}),
    )
    target_values = parsed["target_ids"]
    if not isinstance(target_values, tuple) or not target_values:
        raise ValueError("at least one target is required")
    target_ids = tuple(
        dict.fromkeys(
            _positive_integer(value, "target_ids") for value in target_values
        )
    )
    values: dict[str, object] = {
        "job_name": parsed["job_name"],
        "pipeline_type": pipeline.value,
        "target_ids": tuple(str(value) for value in target_ids),
        "effective_start_at": parsed["effective_start_at"],
        "effective_end_at": parsed["effective_end_at"],
        "daily_window_start": parsed["daily_window_start"],
        "daily_window_end": parsed["daily_window_end"],
        "interval_value": parsed[interval_field],
    }
    return values, pipeline, parsed


async def _strict_form_values(
    request: Request,
    *,
    allowed: frozenset[str],
    repeated: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, str | tuple[str, ...]]:
    form = await request.form()
    collected: dict[str, list[str]] = {}
    for key, value in form.multi_items():
        if key not in allowed:
            raise ValueError("unknown form field")
        if not isinstance(value, str):
            raise ValueError("invalid form field")
        collected.setdefault(key, []).append(value)
    if not optional.issubset(allowed):
        raise ValueError("invalid optional field")
    required = allowed - optional
    if not required.issubset(collected) or not set(collected).issubset(allowed):
        raise ValueError("missing form field")
    result: dict[str, str | tuple[str, ...]] = {}
    for key, values in collected.items():
        if key in repeated:
            result[key] = tuple(values)
        elif len(values) != 1:
            raise ValueError("duplicate form field")
        else:
            result[key] = values[0]
    return result


async def _create_form_echo(
    request: Request,
) -> tuple[PipelineType, dict[str, object]]:
    form = await request.form()
    pipeline = PipelineType.GROUP
    raw_pipeline = form.get("pipeline_type")
    if raw_pipeline == PipelineType.ARTICLE.value:
        pipeline = PipelineType.ARTICLE
    values = _job_form_defaults(pipeline)
    for field in (
        "job_name",
        "effective_start_at",
        "effective_end_at",
        "daily_window_start",
        "daily_window_end",
    ):
        value = form.get(field)
        if isinstance(value, str):
            values[field] = value
    interval_field = (
        "interval_seconds"
        if pipeline is PipelineType.GROUP
        else "interval_minutes"
    )
    interval = form.get(interval_field)
    if isinstance(interval, str):
        values["interval_value"] = interval
    values["target_ids"] = tuple(
        value
        for value in form.getlist("target_ids")
        if isinstance(value, str)
    )
    version = form.get("version")
    if isinstance(version, str):
        values["version"] = version
    return pipeline, values


def _create_command(
    request: Request,
    values: dict[str, object],
    pipeline: PipelineType,
) -> CreateCollectionJobCommand:
    zone = ZoneInfo(request.app.state.config.app.timezone)
    interval = _positive_integer(str(values["interval_value"]), "interval")
    interval_seconds = interval if pipeline is PipelineType.GROUP else interval * 60
    return CreateCollectionJobCommand(
        job_name=str(values["job_name"]),
        pipeline_type=pipeline,
        target_ids=tuple(
            _positive_integer(value, "target_ids")
            for value in values["target_ids"]  # type: ignore[union-attr]
        ),
        effective_start_at=_local_datetime(str(values["effective_start_at"]), zone),
        effective_end_at=_local_datetime(str(values["effective_end_at"]), zone),
        daily_window_start=_local_time(str(values["daily_window_start"])),
        daily_window_end=_local_time(str(values["daily_window_end"])),
        interval_seconds=interval_seconds,
    )


def _update_command(
    request: Request,
    values: dict[str, object],
    pipeline: PipelineType,
) -> UpdateCollectionJobCommand:
    created = _create_command(request, values, pipeline)
    return UpdateCollectionJobCommand(
        job_name=created.job_name,
        pipeline_type=created.pipeline_type,
        target_ids=created.target_ids,
        effective_start_at=created.effective_start_at,
        effective_end_at=created.effective_end_at,
        daily_window_start=created.daily_window_start,
        daily_window_end=created.daily_window_end,
        interval_seconds=created.interval_seconds,
    )


def _single_query_values(
    request: Request, allowed: frozenset[str]
) -> dict[str, str]:
    collected: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed:
            raise ValueError("unknown query field")
        collected.setdefault(key, []).append(value)
    if any(len(values) != 1 for values in collected.values()):
        raise ValueError("duplicate query field")
    return {key: values[0] for key, values in collected.items()}


def _required_pipeline(value: str) -> PipelineType:
    try:
        return PipelineType(value)
    except ValueError as exc:
        raise ValueError("invalid pipeline") from exc


def _optional_pipeline(value: str | None) -> PipelineType | None:
    return None if value in {None, ""} else _required_pipeline(value)


def _optional_status(value: str | None) -> JobStatus | None:
    if value in {None, ""}:
        return None
    try:
        return JobStatus(value)
    except ValueError as exc:
        raise ValueError("invalid status") from exc


def _optional_name(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("invalid name")
    return value


def _optional_date(value: str | None) -> Date | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid date")
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid date") from exc


def _positive_integer(value: str, field: str) -> int:
    if not isinstance(value, str) or _POSITIVE_INTEGER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid positive integer: {field}")
    return int(value)


def _local_datetime(value: str, zone: ZoneInfo) -> datetime:
    if _DATETIME_LOCAL_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid local datetime")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError as exc:
        raise ValueError("invalid local datetime") from exc
    return parsed.replace(tzinfo=zone)


def _local_time(value: str) -> time:
    if _TIME_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid local time")
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("invalid local time") from exc


def _job_list_url(values: dict[str, str], page: int) -> str:
    query_values = {
        key: value
        for key, value in (
            ("pipeline", values.get("pipeline", "")),
            ("status", values.get("status", "")),
            ("date", values.get("date", "")),
            ("name", values.get("name", "")),
            ("page", str(page)),
            ("page_size", values.get("page_size", "20")),
        )
        if value
    }
    return f"/jobs?{urlencode(query_values)}"


def _form_validation_message(exc: ValueError) -> str:
    if "duplicate" in str(exc):
        return "表单包含重复字段，请检查任务参数后重试。"
    return "请检查任务参数后重试。"


def _job_validation_message(
    exc: JobValidationError, pipeline: PipelineType
) -> str:
    message = str(exc)
    if pipeline is PipelineType.ARTICLE and "at least 600" in message:
        return "公众号采集最小间隔为 10 分钟。"
    if pipeline is PipelineType.GROUP and "at least 30" in message:
        return "微信群采集最小间隔为 30 秒。"
    return "请检查任务参数后重试。"


def _now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))
