from __future__ import annotations

import secrets
from datetime import datetime
from typing import Awaitable, Callable
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.middleware.base import BaseHTTPMiddleware


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_INVALID_CSRF_FORM = "\0invalid-csrf-form"


class AdminSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.admin = None
        request.state.csrf_token = None
        if _is_public_request(request):
            return await call_next(request)

        config = request.app.state.config
        auth_service = request.app.state.auth_service
        session_token = request.cookies.get(config.auth.session_cookie_name)
        csrf_cookie = request.cookies.get(config.auth.csrf_cookie_name)
        admin = None
        if session_token:
            admin = auth_service.authenticate(
                session_token,
                csrf_cookie,
                _now(config.app.timezone),
            )
        if admin is None:
            return _unauthenticated_response(request)

        request.state.admin = admin
        request.state.csrf_token = csrf_cookie
        if request.method in UNSAFE_METHODS:
            request_token = await _request_csrf_token(request)
            if request_token == _INVALID_CSRF_FORM:
                return Response("Invalid form fields", status_code=422)
            if (
                not csrf_cookie
                or not request_token
                or not secrets.compare_digest(csrf_cookie, request_token)
                or not auth_service.verify_csrf(
                    session_token,
                    request_token,
                    _now(config.app.timezone),
                )
            ):
                return Response("CSRF validation failed", status_code=403)
        return await call_next(request)


def _is_public_request(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/static/"):
        return True
    if path == "/favicon.ico" and request.method == "GET":
        return True
    if path == "/login" and request.method in {"GET", "POST"}:
        return True
    return path == "/healthz" and request.method == "GET"


def _unauthenticated_response(request: Request) -> Response:
    accept = request.headers.get("accept", "").lower()
    if (
        request.url.path.startswith("/api/")
        or "application/json" in accept
        or "text/event-stream" in accept
    ):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


async def _request_csrf_token(request: Request) -> str | None:
    header_token = request.headers.get("x-csrf-token")
    content_type = request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" in content_type:
        body = await request.body()
        try:
            decoded_body = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        values = parse_qs(decoded_body, keep_blank_values=True)
        tokens = values.get("csrf_token")
        if tokens and len(tokens) != 1:
            return _INVALID_CSRF_FORM
        body_token = tokens[0] if tokens else None
        if header_token and body_token and not secrets.compare_digest(header_token, body_token):
            return _INVALID_CSRF_FORM
        return header_token or body_token
    if "multipart/form-data" in content_type:
        try:
            await request.body()
            form = await request.form()
        except StarletteHTTPException as exc:
            if exc.status_code == 400:
                return None
            raise
        except (MultiPartException, ValueError):
            return None
        values = form.getlist("csrf_token")
        if len(values) > 1 or any(not isinstance(value, str) for value in values):
            return _INVALID_CSRF_FORM
        body_token = values[0] if values else None
        if header_token and body_token and not secrets.compare_digest(header_token, body_token):
            return _INVALID_CSRF_FORM
        return header_token or body_token
    return header_token


def _now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)
