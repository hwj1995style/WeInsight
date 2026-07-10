from __future__ import annotations

import secrets
from collections import deque
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services.auth_service import (
    InvalidCredentialsError,
    LoginLockedError,
    PasswordValidationError,
)


LOGIN_CSRF_COOKIE = "login_csrf"
LOGIN_CSRF_MAX_AGE_SECONDS = 20 * 60
MAX_CONCURRENT_LOGIN_HASHES = 2
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()


class LoginAttemptLimiter:
    def __init__(self, limit: int, window_minutes: int) -> None:
        self.limit = limit
        self.window = timedelta(minutes=window_minutes)
        self._attempts: dict[str, deque[datetime]] = {}
        self._lock = Lock()

    def reserve(self, client_ip: str, now: datetime) -> bool:
        cutoff = now - self.window
        with self._lock:
            attempts = self._attempts.setdefault(client_ip, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True

    def reset(self, client_ip: str) -> None:
        with self._lock:
            self._attempts.pop(client_ip, None)


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    token = secrets.token_urlsafe(32)
    response = _login_response(
        request,
        login_csrf=token,
        password_changed=request.query_params.get("password_changed") == "1",
    )
    response.set_cookie(
        LOGIN_CSRF_COOKIE,
        token,
        max_age=LOGIN_CSRF_MAX_AGE_SECONDS,
        httponly=False,
        secure=request.app.state.config.web.secure_cookie,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    form = await request.form()
    cookie_token = request.cookies.get(LOGIN_CSRF_COOKIE)
    form_token = form.get("login_csrf")
    if (
        not cookie_token
        or not isinstance(form_token, str)
        or not secrets.compare_digest(cookie_token, form_token)
    ):
        return Response("CSRF validation failed", status_code=403)

    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    now = _now(request)
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.login_attempt_limiter
    if not limiter.reserve(client_ip, now):
        response = _login_response(
            request,
            login_csrf=cookie_token,
            error="用户名或密码错误，或账户暂时不可用",
            status_code=429,
        )
        response.headers["Retry-After"] = str(
            request.app.state.config.auth.login_lock_minutes * 60
        )
        return response
    try:
        async with request.app.state.login_hash_semaphore:
            session = await run_in_threadpool(
                request.app.state.auth_service.login,
                username,
                password,
                client_ip,
                request.headers.get("user-agent", ""),
                now,
            )
    except (InvalidCredentialsError, LoginLockedError):
        return _login_response(
            request,
            login_csrf=cookie_token,
            error="用户名或密码错误，或账户暂时不可用",
            status_code=401,
        )

    config = request.app.state.config
    limiter.reset(client_ip)
    response = RedirectResponse("/", status_code=303)
    max_age = max(0, int((session.expires_at - _now(request)).total_seconds()))
    response.set_cookie(
        config.auth.session_cookie_name,
        session.session_token,
        max_age=max_age,
        httponly=True,
        secure=config.web.secure_cookie,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        config.auth.csrf_cookie_name,
        session.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=config.web.secure_cookie,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    return response


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"view": "home"},
    )


@router.get("/account/password", response_class=HTMLResponse)
async def password_page(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"view": "password"},
    )


@router.post("/account/password", response_class=HTMLResponse)
async def change_password(request: Request) -> Response:
    form = await request.form()
    try:
        request.app.state.auth_service.change_password(
            request.state.admin.id,
            str(form.get("current_password", "")),
            str(form.get("new_password", "")),
            _now(request),
        )
    except PasswordValidationError:
        return _password_error(request, "新密码至少需要 12 个字符")
    except InvalidCredentialsError:
        return _password_error(request, "当前密码不正确")

    response = RedirectResponse("/login?password_changed=1", status_code=303)
    _delete_auth_cookies(response, request)
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    config = request.app.state.config
    session_token = request.cookies.get(config.auth.session_cookie_name)
    if session_token:
        request.app.state.auth_service.logout(session_token, _now(request))
    response = RedirectResponse("/login", status_code=303)
    _delete_auth_cookies(response, request)
    return response


def _login_response(
    request: Request,
    *,
    login_csrf: str,
    error: str | None = None,
    password_changed: bool = False,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "login_csrf": login_csrf,
            "error": error,
            "password_changed": password_changed,
        },
        status_code=status_code,
    )


def _password_error(request: Request, message: str) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"view": "password", "error": message},
        status_code=400,
    )


def _delete_auth_cookies(response: Response, request: Request) -> None:
    config = request.app.state.config
    response.delete_cookie(config.auth.session_cookie_name, path="/")
    response.delete_cookie(config.auth.csrf_cookie_name, path="/")


def _now(request: Request) -> datetime:
    timezone_name = request.app.state.config.app.timezone
    return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)
