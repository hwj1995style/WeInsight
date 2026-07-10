from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.services.runtime_monitor_service import RuntimeDashboardSnapshot


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    snapshot = await run_in_threadpool(
        request.app.state.dashboard_service.get_snapshot,
        24,
    )
    chart_data = {
        "categories": ["微信群", "公众号"],
        "success": [
            snapshot.group_collection.success,
            snapshot.article_collection.success,
        ],
        "failed": [
            snapshot.group_collection.failed,
            snapshot.article_collection.failed,
        ],
        "skipped": [
            snapshot.group_collection.skipped,
            snapshot.article_collection.skipped,
        ],
    }
    chart_summary = (
        f"最近 24 小时采集结果构成（仅明确终态）："
        f"微信群成功 {snapshot.group_collection.success}，"
        f"失败 {snapshot.group_collection.failed}，跳过 {snapshot.group_collection.skipped}；"
        f"公众号成功 {snapshot.article_collection.success}，"
        f"失败 {snapshot.article_collection.failed}，跳过 {snapshot.article_collection.skipped}。"
    )
    now = datetime.now(ZoneInfo(request.app.state.config.app.timezone))
    runtime_available = True
    try:
        runtime = await run_in_threadpool(
            request.app.state.runtime_monitor_service.get_dashboard,
            now,
        )
    except Exception:
        runtime = RuntimeDashboardSnapshot.empty(now)
        runtime_available = False
    trend_data = {
        "categories": [
            bucket.bucket_start.strftime("%m-%d %H:00")
            for bucket in runtime.trend
        ],
        "successful": [bucket.successful_count for bucket in runtime.trend],
        "failed": [bucket.unsuccessful_count for bucket in runtime.trend],
        "cancelled": [bucket.cancelled_count for bucket in runtime.trend],
    }
    trend_summary = (
        "最近 24 小时明确终态运行："
        f"成功 {sum(trend_data['successful'])}，"
        f"失败或异常终止 {sum(trend_data['failed'])}，"
        f"取消 {sum(trend_data['cancelled'])}。"
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "section": "dashboard",
            "snapshot": snapshot,
            "chart_data": chart_data,
            "chart_summary": chart_summary,
            "runtime": runtime,
            "runtime_available": runtime_available,
            "trend_data": trend_data,
            "trend_summary": trend_summary,
        },
    )
