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
    workers_by_type = {worker.worker_type: worker for worker in runtime.workers}
    wechat_status_label = (
        {
            "ok": "正常",
            "not_running": "未运行",
            "not_logged_in": "未登录",
            "version_mismatch": "版本不匹配",
            "window_unavailable": "窗口不可用",
            "rpa_unavailable": "自动化不可用",
        }.get(runtime.latest_wechat_status.value, "异常")
        if runtime.latest_wechat_status
        else "暂无"
    )
    worker_cards = tuple(
        {
            "worker_type": worker_type,
            "label": label,
            "worker": workers_by_type.get(worker_type),
        }
        for worker_type, label in (
            ("pipeline", "Pipeline"),
            ("collector", "Collector"),
        )
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
            "wechat_status_label": wechat_status_label,
            "worker_cards": worker_cards,
            "trend_data": trend_data,
            "trend_summary": trend_summary,
        },
    )
