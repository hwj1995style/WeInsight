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


LEGACY_LOGIN_CSRF_COOKIE = "login_csrf"
LOGIN_CSRF_MAX_AGE_SECONDS = 20 * 60
LOGIN_CSRF_TOKEN_BYTES = 32
LOGIN_CSRF_TOKEN_LENGTH = 43
MAX_CONCURRENT_LOGIN_HASHES = 2
MAX_TRACKED_LOGIN_IPS = 4096
LOGIN_LIMITER_CLEANUP_INTERVAL = timedelta(minutes=1)
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()


class LoginAttemptLimiter:
    def __init__(
        self,
        limit: int,
        window_minutes: int,
        max_tracked_ips: int = MAX_TRACKED_LOGIN_IPS,
    ) -> None:
        self.limit = limit
        self.window = timedelta(minutes=window_minutes)
        self.max_tracked_ips = max_tracked_ips
        self._attempts: dict[str, deque[datetime]] = {}
        self._lock = Lock()
        self._next_cleanup_at: datetime | None = None

    def reserve(self, client_ip: str, now: datetime) -> bool:
        cutoff = now - self.window
        with self._lock:
            if self._next_cleanup_at is None or now >= self._next_cleanup_at:
                self._prune_expired(cutoff)
                self._next_cleanup_at = now + min(
                    self.window,
                    LOGIN_LIMITER_CLEANUP_INTERVAL,
                )
            attempts = self._attempts.get(client_ip)
            if attempts is None:
                if len(self._attempts) >= self.max_tracked_ips:
                    self._prune_expired(cutoff)
                    if len(self._attempts) >= self.max_tracked_ips:
                        return False
                attempts = deque()
                self._attempts[client_ip] = attempts
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True

    def reset(self, client_ip: str) -> None:
        with self._lock:
            self._attempts.pop(client_ip, None)

    @property
    def tracked_ip_count(self) -> int:
        with self._lock:
            return len(self._attempts)

    def _prune_expired(self, cutoff: datetime) -> None:
        for client_ip, attempts in list(self._attempts.items()):
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                self._attempts.pop(client_ip, None)


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    cookie_name = request.app.state.config.auth.login_csrf_cookie_name
    current_token = request.cookies.get(cookie_name)
    token = (
        current_token
        if _valid_login_csrf_token(current_token)
        else _new_login_csrf_token()
    )
    response = _login_response(
        request,
        login_csrf=token,
        password_changed=request.query_params.get("password_changed") == "1",
    )
    _set_login_csrf_cookie(response, request, token)
    _delete_legacy_login_csrf_cookie(response, cookie_name)
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    form = await request.form()
    cookie_name = request.app.state.config.auth.login_csrf_cookie_name
    cookie_token = request.cookies.get(cookie_name)
    form_token = form.get("login_csrf")
    if (
        not _valid_login_csrf_token(cookie_token)
        or not isinstance(form_token, str)
        or not secrets.compare_digest(cookie_token, form_token)
    ):
        return _login_csrf_failure_response(request)

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
    response = RedirectResponse("/dashboard", status_code=303)
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
    response.delete_cookie(cookie_name, path="/")
    _delete_legacy_login_csrf_cookie(response, cookie_name)
    return response


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Response:
    return RedirectResponse("/dashboard", status_code=303)


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


def _login_csrf_failure_response(request: Request) -> Response:
    token = _new_login_csrf_token()
    response = _login_response(
        request,
        login_csrf=token,
        error="登录页面已过期或在其他窗口被刷新，请重新提交。",
        status_code=403,
    )
    _set_login_csrf_cookie(response, request, token)
    _delete_legacy_login_csrf_cookie(
        response,
        request.app.state.config.auth.login_csrf_cookie_name,
    )
    return response


def _new_login_csrf_token() -> str:
    return secrets.token_urlsafe(LOGIN_CSRF_TOKEN_BYTES)


def _valid_login_csrf_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == LOGIN_CSRF_TOKEN_LENGTH
        and value.isascii()
        and all(character.isalnum() or character in "-_" for character in value)
    )


def _set_login_csrf_cookie(
    response: Response,
    request: Request,
    token: str,
) -> None:
    response.set_cookie(
        request.app.state.config.auth.login_csrf_cookie_name,
        token,
        max_age=LOGIN_CSRF_MAX_AGE_SECONDS,
        httponly=False,
        secure=request.app.state.config.web.secure_cookie,
        samesite="strict",
        path="/",
    )


def _delete_legacy_login_csrf_cookie(
    response: Response,
    current_cookie_name: str,
) -> None:
    if current_cookie_name != LEGACY_LOGIN_CSRF_COOKIE:
        response.delete_cookie(LEGACY_LOGIN_CSRF_COOKIE, path="/")


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
