from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse


router = APIRouter()


@router.get("/workers")
async def worker_status() -> RedirectResponse:
    return RedirectResponse("/dashboard#worker-status", status_code=303)
