from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()


@router.get("/workers", response_class=HTMLResponse)
async def worker_status(request: Request) -> Response:
    zone = ZoneInfo(request.app.state.config.app.timezone)
    snapshot = await run_in_threadpool(
        request.app.state.runtime_monitor_service.get_workers,
        datetime.now(zone),
    )
    return templates.TemplateResponse(
        request=request,
        name="workers/status.html",
        context={
            "section": "workers",
            "snapshot": snapshot,
        },
    )
