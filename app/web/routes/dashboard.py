from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates


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
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "section": "dashboard",
            "snapshot": snapshot,
            "chart_data": chart_data,
            "chart_summary": chart_summary,
        },
    )
