from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.services.auth_service import (
    AuthenticatedAdmin,
    AuthenticatedSession,
    InvalidCredentialsError,
    LoginLockedError,
    PasswordValidationError,
)
from app.web.app import create_app
from app.web.routes import auth as auth_routes


class FakeAuthService:
    def __init__(self) -> None:
        self.admin = AuthenticatedAdmin(
            id=1,
            username="admin",
            using_default_password=True,
        )
        self.login_error: Exception | None = None
        self.change_password_error: Exception | None = None
        self.allow_csrf = True
        self.revoked = False
        self.login_calls: list[tuple[str, str, str, str, datetime]] = []
        self.authenticate_calls: list[tuple[str, str | None, datetime]] = []
        self.verify_csrf_calls: list[tuple[str, str, datetime]] = []
        self.logout_calls: list[tuple[str, datetime]] = []
        self.change_password_calls: list[tuple[int, str, str, datetime]] = []

    def login(
        self,
        username: str,
        password: str,
        client_ip: str,
        user_agent: str,
        now: datetime,
    ) -> AuthenticatedSession:
        self.login_calls.append((username, password, client_ip, user_agent, now))
        if self.login_error is not None:
            raise self.login_error
        self.revoked = False
        return AuthenticatedSession(
            admin=self.admin,
            session_token="session-token",
            csrf_token="csrf-token",
            expires_at=now + timedelta(hours=24),
        )

    def authenticate(
        self,
        session_token: str,
        csrf_token: str | None,
        now: datetime,
    ) -> AuthenticatedAdmin | None:
        self.authenticate_calls.append((session_token, csrf_token, now))
        if self.revoked or session_token != "session-token":
            return None
        if csrf_token is not None and csrf_token != "csrf-token":
            return None
        return self.admin

    def verify_csrf(
        self,
        session_token: str,
        csrf_token: str,
        now: datetime,
    ) -> bool:
        self.verify_csrf_calls.append((session_token, csrf_token, now))
        return (
            self.allow_csrf
            and session_token == "session-token"
            and csrf_token == "csrf-token"
        )

    def logout(self, session_token: str, now: datetime) -> None:
        self.logout_calls.append((session_token, now))
        self.revoked = True

    def change_password(
        self,
        admin_id: int,
        current_password: str,
        new_password: str,
        now: datetime,
    ) -> None:
        self.change_password_calls.append(
            (admin_id, current_password, new_password, now)
        )
        if self.change_password_error is not None:
            raise self.change_password_error
        self.revoked = True


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def auth_service() -> FakeAuthService:
    return FakeAuthService()


@pytest.fixture
def app(config: Config, auth_service: FakeAuthService) -> FastAPI:
    return create_app(config, auth_service=auth_service)


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(raw_client: TestClient) -> TestClient:
    response = raw_client.get("/login")
    assert response.status_code == 200
    return raw_client


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "admin123456",
            "login_csrf": client.cookies["login_csrf"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def _set_cookie_header(response: object, cookie_name: str) -> str:
    headers = response.headers.get_list("set-cookie")  # type: ignore[attr-defined]
    for header in headers:
        if header.startswith(f"{cookie_name}="):
            return header.lower()
    raise AssertionError(f"missing Set-Cookie header for {cookie_name}")


def _login(client: TestClient, *, username: str, password: str) -> object:
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "login_csrf": client.cookies["login_csrf"],
        },
        follow_redirects=False,
    )


def test_anonymous_home_redirects_to_login(raw_client: TestClient) -> None:
    response = raw_client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize(
    "accept",
    [
        "application/json",
        "application/json; charset=utf-8",
        "text/plain, application/json;q=0.9",
        "text/event-stream",
    ],
)
def test_anonymous_json_and_sse_requests_get_401(
    raw_client: TestClient,
    accept: str,
) -> None:
    response = raw_client.get("/", headers={"Accept": accept})

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_public_get_routes_and_static_files_bypass_authentication(
    raw_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    assert raw_client.get("/login").status_code == 200
    assert raw_client.get("/healthz").status_code == 200
    css = raw_client.get("/static/app.css")

    assert css.status_code == 200
    assert "--color-accent" in css.text
    assert auth_service.authenticate_calls == []


def test_favicon_request_does_not_rotate_login_csrf_cookie(
    raw_client: TestClient,
) -> None:
    raw_client.get("/login")
    login_csrf = raw_client.cookies["login_csrf"]

    response = raw_client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code == 204
    assert raw_client.cookies["login_csrf"] == login_csrf


def test_login_csrf_cookie_is_strict_readable_and_lasts_twenty_minutes(
    raw_client: TestClient,
) -> None:
    response = raw_client.get("/login")
    cookie = _set_cookie_header(response, "login_csrf")

    assert "max-age=1200" in cookie
    assert "path=/" in cookie
    assert "samesite=strict" in cookie
    assert "httponly" not in cookie
    assert "secure" not in cookie
    assert raw_client.cookies["login_csrf"] in response.text


@pytest.mark.parametrize("secure_cookie", [False, True])
def test_session_and_csrf_cookie_security_flags_follow_config(
    config: Config,
    auth_service: FakeAuthService,
    secure_cookie: bool,
) -> None:
    configured = replace(
        config,
        web=replace(config.web, secure_cookie=secure_cookie),
    )
    scheme = "https" if secure_cookie else "http"
    with TestClient(
        create_app(configured, auth_service=auth_service),
        base_url=f"{scheme}://testserver",
    ) as secure_client:
        login_page = secure_client.get("/login")
        login_cookie = _set_cookie_header(login_page, "login_csrf")
        response = _login(
            secure_client,
            username="admin",
            password="admin123456",
        )

    session_cookie = _set_cookie_header(response, config.auth.session_cookie_name)
    csrf_cookie = _set_cookie_header(response, config.auth.csrf_cookie_name)
    for cookie in (login_cookie, session_cookie, csrf_cookie):
        assert "path=/" in cookie
        assert "samesite=strict" in cookie
        assert ("secure" in cookie) is secure_cookie
    assert "httponly" in session_cookie
    assert "httponly" not in csrf_cookie
    assert "httponly" not in login_cookie


@pytest.mark.parametrize(
    ("include_cookie", "form_token"),
    [
        (True, None),
        (True, "wrong-login-token"),
        (False, "orphan-login-token"),
    ],
)
def test_login_rejects_missing_or_mismatched_double_submit_token(
    app: FastAPI,
    auth_service: FakeAuthService,
    include_cookie: bool,
    form_token: str | None,
) -> None:
    with TestClient(app) as test_client:
        if include_cookie:
            test_client.get("/login")
        data = {"username": "admin", "password": "admin123456"}
        if form_token is not None:
            data["login_csrf"] = form_token
        response = test_client.post("/login", data=data)

    assert response.status_code == 403
    assert auth_service.login_calls == []


def test_login_rejects_an_expired_cookie_not_sent_by_the_browser(
    app: FastAPI,
    auth_service: FakeAuthService,
) -> None:
    with TestClient(app) as test_client:
        test_client.get("/login")
        token = test_client.cookies["login_csrf"]
        test_client.cookies.delete("login_csrf")
        response = test_client.post(
            "/login",
            data={
                "username": "admin",
                "password": "admin123456",
                "login_csrf": token,
            },
        )

    assert response.status_code == 403
    assert auth_service.login_calls == []


def test_login_uses_constant_time_token_comparison(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compare_digest = secrets.compare_digest
    comparisons: list[tuple[str, str]] = []

    def tracked_compare_digest(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return real_compare_digest(left, right)

    monkeypatch.setattr(auth_routes.secrets, "compare_digest", tracked_compare_digest)

    response = _login(client, username="admin", password="admin123456")

    assert response.status_code == 303
    assert comparisons


def test_login_failures_use_one_non_disclosing_response(
    client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    auth_service.login_error = InvalidCredentialsError("account detail must not leak")

    unknown = _login(client, username="unknown-account", password="guess-one")
    known = _login(client, username="admin", password="guess-two")

    for response in (unknown, known):
        assert response.status_code == 401
        assert "用户名或密码错误，或账户暂时不可用" in response.text
        assert "account detail must not leak" not in response.text
        assert "guess-one" not in response.text
        assert "guess-two" not in response.text
        assert "unknown-account" not in response.text


def test_locked_login_uses_the_same_non_disclosing_message(
    client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    auth_service.login_error = LoginLockedError(datetime(2026, 7, 10, 12, 0))

    response = _login(client, username="admin", password="wrong-password")

    assert response.status_code == 401
    assert "用户名或密码错误，或账户暂时不可用" in response.text
    assert "2026-07-10" not in response.text


def test_default_admin_can_login_without_forced_change(client: TestClient) -> None:
    response = _login(client, username="admin", password="admin123456")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    home = client.get("/")
    assert "当前仍使用默认密码" in home.text
    assert "必须修改密码后继续" not in home.text


def test_authenticated_request_receives_admin_and_csrf_state(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    response = authenticated_client.get("/")

    assert response.status_code == 200
    assert "admin" in response.text
    assert "csrf-token" in response.text
    session_token, csrf_token, _ = auth_service.authenticate_calls[-1]
    assert session_token == "session-token"
    assert csrf_token == "csrf-token"


def test_jinja_templates_escape_admin_controlled_text(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    auth_service.admin = AuthenticatedAdmin(
        id=1,
        username="<script>alert(1)</script>",
        using_default_password=False,
    )

    response = authenticated_client.get("/")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_without_csrf_is_rejected(
    authenticated_client: TestClient,
    method: str,
) -> None:
    response = authenticated_client.request(method, "/not-a-route")

    assert response.status_code == 403


def test_csrf_requires_the_cookie_even_when_header_is_present(
    authenticated_client: TestClient,
    config: Config,
    auth_service: FakeAuthService,
) -> None:
    authenticated_client.cookies.delete(config.auth.csrf_cookie_name)

    response = authenticated_client.post(
        "/logout",
        headers={"X-CSRF-Token": "csrf-token"},
    )

    assert response.status_code == 403
    assert auth_service.verify_csrf_calls == []


def test_post_without_csrf_is_rejected(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    response = authenticated_client.post("/logout")

    assert response.status_code == 403
    assert auth_service.verify_csrf_calls == []


def test_malformed_form_body_is_rejected_instead_of_raising_500(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/logout",
        content=b"\xff",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 403


def test_csrf_rejects_mismatched_cookie_and_request_token(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    response = authenticated_client.post(
        "/logout",
        headers={"X-CSRF-Token": "wrong-token"},
    )

    assert response.status_code == 403
    assert auth_service.verify_csrf_calls == []


def test_csrf_rejects_when_auth_service_verification_fails(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    auth_service.allow_csrf = False

    response = authenticated_client.post(
        "/logout",
        headers={"X-CSRF-Token": "csrf-token"},
    )

    assert response.status_code == 403
    assert len(auth_service.verify_csrf_calls) == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_accepts_a_verified_header_token(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
    method: str,
) -> None:
    response = authenticated_client.request(
        method,
        "/not-a-route",
        headers={"X-CSRF-Token": "csrf-token"},
    )

    assert response.status_code == 404
    assert len(auth_service.verify_csrf_calls) == 1


def test_form_csrf_parsing_does_not_consume_password_route_body(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
) -> None:
    response = authenticated_client.post(
        "/account/password",
        data={
            "current_password": "admin123456",
            "new_password": "a-secure-new-password",
            "csrf_token": "csrf-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?password_changed=1"
    admin_id, current_password, new_password, _ = (
        auth_service.change_password_calls[-1]
    )
    assert (admin_id, current_password, new_password) == (
        1,
        "admin123456",
        "a-secure-new-password",
    )


@pytest.mark.parametrize(
    ("error", "visible_message"),
    [
        (
            PasswordValidationError("new password must be at least 12 characters"),
            "新密码至少需要 12 个字符",
        ),
        (InvalidCredentialsError("current password is invalid"), "当前密码不正确"),
    ],
)
def test_password_validation_errors_are_safe_and_keep_the_form_available(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
    error: Exception,
    visible_message: str,
) -> None:
    auth_service.change_password_error = error

    response = authenticated_client.post(
        "/account/password",
        data={
            "current_password": "old-secret-value",
            "new_password": "new-secret-value",
            "csrf_token": "csrf-token",
        },
    )

    assert response.status_code == 400
    assert visible_message in response.text
    assert "old-secret-value" not in response.text
    assert "new-secret-value" not in response.text
    assert "csrf-token" in response.text


def test_logout_revokes_session_and_deletes_auth_cookies(
    authenticated_client: TestClient,
    auth_service: FakeAuthService,
    config: Config,
) -> None:
    response = authenticated_client.post(
        "/logout",
        headers={"X-CSRF-Token": "csrf-token"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert auth_service.logout_calls[-1][0] == "session-token"
    for name in (config.auth.session_cookie_name, config.auth.csrf_cookie_name):
        cookie = _set_cookie_header(response, name)
        assert "max-age=0" in cookie
        assert "path=/" in cookie
        assert name not in authenticated_client.cookies


def test_password_change_revokes_browser_session_and_shows_login_success(
    authenticated_client: TestClient,
    config: Config,
) -> None:
    response = authenticated_client.post(
        "/account/password",
        data={
            "current_password": "admin123456",
            "new_password": "a-secure-new-password",
            "csrf_token": "csrf-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert config.auth.session_cookie_name not in authenticated_client.cookies
    assert config.auth.csrf_cookie_name not in authenticated_client.cookies
    login = authenticated_client.get(response.headers["location"])
    assert "密码已修改，请重新登录" in login.text


def test_template_and_static_paths_do_not_depend_on_current_directory(
    config: Config,
    auth_service: FakeAuthService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(config, auth_service=auth_service)

    with TestClient(app) as test_client:
        assert test_client.get("/login").status_code == 200
        assert test_client.get("/static/app.css").status_code == 200
