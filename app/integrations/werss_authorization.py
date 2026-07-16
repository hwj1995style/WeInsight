from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from app.domain.werss_authorization import WeRSSAuthorizationUpstreamState


class WeRSSAuthorizationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class QrStart:
    image_url: str


@dataclass(frozen=True, slots=True)
class QrStatus:
    status: str


class WeRSSAuthorizationClient:
    def __init__(
        self,
        base_url: str,
        access_key: str,
        secret_key: str,
        management_username: str,
        management_password: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10,
        qr_ready_timeout_seconds: float = 60,
    ) -> None:
        if base_url != "http://127.0.0.1:8001":
            raise ValueError("WeRSS authorization endpoint must be loopback:8001")
        self._base_url = base_url
        self._catalog_authorization = f"AK-SK {access_key}:{secret_key}"
        self._username = management_username
        self._password = management_password
        self._transport = transport
        self._timeout = timeout_seconds
        self._qr_ready_timeout = qr_ready_timeout_seconds
        self._jwt: str | None = None
        self._jwt_expires_at: datetime | None = None
        self._lock = threading.Lock()

    @property
    def scan_configured(self) -> bool:
        return bool(self._password)

    def set_management_credentials(self, username: str, password: str | None) -> None:
        if not isinstance(username, str) or not username or username != username.strip():
            raise ValueError("management username must be non-empty trimmed text")
        with self._lock:
            if username == self._username and password == self._password:
                return
            self._username = username
            self._password = password
            self._jwt = None
            self._jwt_expires_at = None

    def verify_management_credentials(self, now: datetime) -> None:
        token = self._bearer_token(now)
        payload = self._json_request(
            "GET",
            "/api/v1/wx/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = _success_data(payload)
        if not isinstance(data, dict) or data.get("is_valid") is not True:
            raise WeRSSAuthorizationError("werss_authorization_auth_failed")

    def fetch_status(self) -> WeRSSAuthorizationUpstreamState:
        payload = self._json_request(
            "GET",
            "/api/v1/wx/sys/info",
            headers={"Authorization": self._catalog_authorization},
        )
        data = _success_data(payload)
        wx = data.get("wx")
        if not isinstance(wx, dict) or type(wx.get("login")) is not bool:
            raise WeRSSAuthorizationError("werss_authorization_invalid")
        info = wx.get("info")
        if info is not None and not isinstance(info, dict):
            raise WeRSSAuthorizationError("werss_authorization_invalid")
        info = info or {}
        ext_data = info.get("ext_data")
        if ext_data is not None and not isinstance(ext_data, dict):
            raise WeRSSAuthorizationError("werss_authorization_invalid")
        account_name = (ext_data or {}).get("wx_app_name")
        if account_name == "":
            account_name = None
        elif account_name is not None:
            if not isinstance(account_name, str) or not account_name.strip() or len(account_name) > 200:
                raise WeRSSAuthorizationError("werss_authorization_invalid")
            account_name = account_name.strip()
        expiry = info.get("expiry")
        if expiry is not None and not isinstance(expiry, dict):
            raise WeRSSAuthorizationError("werss_authorization_invalid")
        expiry_text = (expiry or {}).get("expiry_time") or wx.get("expiry_time")
        expires_at = _parse_expiry(expiry_text)
        return WeRSSAuthorizationUpstreamState(wx["login"], account_name, expires_at)

    def start_qr(self, now: datetime) -> QrStart:
        payload = self._management_json("GET", "/api/v1/wx/auth/qr/code", now)
        data = _success_data(payload)
        image_url = data.get("code") if isinstance(data, dict) else None
        normalized_url = _normalize_qr_url(image_url)
        if normalized_url is None:
            raise WeRSSAuthorizationError("werss_qr_invalid")
        self._wait_for_qr_image(now)
        return QrStart(normalized_url)

    def _wait_for_qr_image(self, now: datetime) -> None:
        deadline = time.monotonic() + max(self._qr_ready_timeout, 10)
        while True:
            payload = self._management_json("GET", "/api/v1/wx/auth/qr/image", now)
            ready = _success_data(payload)
            if ready is True:
                return
            if ready is not False:
                raise WeRSSAuthorizationError("werss_qr_invalid")
            if time.monotonic() >= deadline:
                raise WeRSSAuthorizationError("werss_qr_timeout")
            time.sleep(0.25)

    def fetch_qr_image(self, image_url: str) -> tuple[bytes, str]:
        if not _allowed_qr_url(image_url):
            raise WeRSSAuthorizationError("werss_qr_invalid")
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(image_url)
        except httpx.TimeoutException:
            raise WeRSSAuthorizationError("werss_qr_timeout") from None
        except httpx.HTTPError:
            raise WeRSSAuthorizationError("werss_qr_unavailable") from None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if response.status_code != 200 or content_type not in {"image/png", "image/jpeg"}:
            raise WeRSSAuthorizationError("werss_qr_invalid")
        if not response.content or len(response.content) > 1_048_576:
            raise WeRSSAuthorizationError("werss_qr_invalid")
        return response.content, content_type

    def qr_status(self, now: datetime) -> QrStatus:
        payload = self._management_json("GET", "/api/v1/wx/auth/qr/status", now)
        data = _success_data(payload)
        if not isinstance(data, dict):
            raise WeRSSAuthorizationError("werss_qr_invalid")
        if data.get("login_status") is True:
            return QrStatus("authorized")
        if data.get("qr_code") is False:
            return QrStatus("expired")
        return QrStatus("waiting")

    def close_qr(self, now: datetime) -> None:
        self._management_json("GET", "/api/v1/wx/auth/qr/over", now)

    def _management_json(self, method: str, path: str, now: datetime) -> Any:
        token = self._bearer_token(now)
        try:
            return self._json_request(method, path, headers={"Authorization": f"Bearer {token}"})
        except WeRSSAuthorizationError as exc:
            if exc.code != "werss_authorization_auth_failed":
                raise
        with self._lock:
            self._jwt = None
            self._jwt_expires_at = None
        token = self._bearer_token(now)
        return self._json_request(method, path, headers={"Authorization": f"Bearer {token}"})

    def _bearer_token(self, now: datetime) -> str:
        if not self._password:
            raise WeRSSAuthorizationError("werss_scan_not_configured")
        with self._lock:
            if self._jwt and self._jwt_expires_at and now < self._jwt_expires_at - timedelta(minutes=5):
                return self._jwt
            payload = self._json_request(
                "POST",
                "/api/v1/wx/auth/token",
                data={"username": self._username, "password": self._password},
            )
            if not isinstance(payload, dict):
                raise WeRSSAuthorizationError("werss_authorization_auth_failed")
            token = payload.get("access_token")
            expires_in = payload.get("expires_in")
            if not isinstance(token, str) or not token or type(expires_in) is not int or expires_in < 60:
                raise WeRSSAuthorizationError("werss_authorization_auth_failed")
            self._jwt = token
            self._jwt_expires_at = now + timedelta(seconds=expires_in)
            return token

    def _json_request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.request(method, f"{self._base_url}{path}", **kwargs)
        except httpx.TimeoutException:
            raise WeRSSAuthorizationError("werss_authorization_timeout") from None
        except httpx.HTTPError:
            raise WeRSSAuthorizationError("werss_authorization_unavailable") from None
        if response.status_code in {401, 403}:
            raise WeRSSAuthorizationError("werss_authorization_auth_failed")
        if response.is_redirect or response.status_code >= 400 or len(response.content) > 1_048_576:
            raise WeRSSAuthorizationError("werss_authorization_unavailable")
        try:
            return response.json()
        except ValueError:
            raise WeRSSAuthorizationError("werss_authorization_invalid") from None


def _success_data(payload: Any) -> Any:
    if not isinstance(payload, dict) or payload.get("code") != 0 or "data" not in payload:
        raise WeRSSAuthorizationError("werss_authorization_invalid")
    return payload["data"]


def _parse_expiry(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise WeRSSAuthorizationError("werss_authorization_invalid")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise WeRSSAuthorizationError("werss_authorization_invalid") from None


def _normalize_qr_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        return None
    resolved = urljoin("http://127.0.0.1:8001/", value)
    return resolved if _allowed_qr_url(resolved) else None


def _allowed_qr_url(value: str) -> bool:
    parsed = urlsplit(value)
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    timestamp = query.get("t", [])
    safe_query = not query or (
        set(query) == {"t"}
        and len(timestamp) == 1
        and timestamp[0].replace(".", "", 1).isdigit()
    )
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port == 8001
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path.startswith("/static/")
        and "%" not in parsed.path
        and "\\" not in parsed.path
        and safe_query
    )
