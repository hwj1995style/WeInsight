from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.domain.werss_authorization import (
    WeRSSAuthorizationSnapshot,
    WeRSSAuthorizationUpstreamState,
)
from app.integrations.werss_authorization import (
    WeRSSAuthorizationClient,
    WeRSSAuthorizationError,
)
from app.services.werss_authorization_service import WeRSSAuthorizationService


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 16, 10, 0, 0, tzinfo=ZONE)


def _client(handler, password=None):
    return WeRSSAuthorizationClient(
        "http://127.0.0.1:8001",
        "WK-test",
        "SK-test",
        "controller",
        password,
        transport=httpx.MockTransport(handler),
    )


def test_status_client_returns_only_whitelisted_fields() -> None:
    def handler(request):
        assert request.url.path == "/api/v1/wx/sys/info"
        assert request.headers["Authorization"] == "AK-SK WK-test:SK-test"
        return httpx.Response(200, json={
            "code": 0,
            "data": {"wx": {
                "login": True,
                "token": "must-not-leak",
                "info": {
                    "token": "must-not-leak-either",
                    "cookie": "secret-cookie",
                    "expiry": {"expiry_time": "2026-07-17 09:00:00"},
                    "ext_data": {"wx_app_name": "测试公众号"},
                },
            }},
        })

    state = _client(handler).fetch_status()

    assert state == WeRSSAuthorizationUpstreamState(
        True, "测试公众号", datetime(2026, 7, 17, 9, 0, 0)
    )
    assert "token" not in state.__slots__
    assert "cookie" not in state.__slots__


def test_status_client_rejects_invalid_expiry() -> None:
    client = _client(lambda request: httpx.Response(200, json={
        "code": 0,
        "data": {"wx": {"login": True, "info": {"expiry": {"expiry_time": "tomorrow"}}}},
    }))

    try:
        client.fetch_status()
    except WeRSSAuthorizationError as exc:
        assert exc.code == "werss_authorization_invalid"
    else:
        raise AssertionError("invalid expiry must be rejected")


def test_qr_requires_separate_management_password() -> None:
    client = _client(lambda request: httpx.Response(500), password=None)

    try:
        client.start_qr(NOW)
    except WeRSSAuthorizationError as exc:
        assert exc.code == "werss_scan_not_configured"
    else:
        raise AssertionError("scan must require management credentials")


def test_qr_login_token_stays_internal_and_only_allows_loopback_static_image() -> None:
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/api/v1/wx/auth/token":
            return httpx.Response(200, json={
                "access_token": "secret-jwt",
                "token_type": "bearer",
                "expires_in": 3600,
            })
        if request.url.path == "/api/v1/wx/auth/qr/code":
            return httpx.Response(200, json={
                "code": 0,
                "data": {"code": "static/wx_qrcode.png?t=1784200044.074017"},
            })
        if request.url.path == "/api/v1/wx/auth/qr/image":
            return httpx.Response(200, json={"code": 0, "data": True})
        raise AssertionError(request.url)

    started = _client(handler, password="management-password").start_qr(NOW)

    assert started.image_url == (
        "http://127.0.0.1:8001/static/wx_qrcode.png?t=1784200044.074017"
    )
    assert calls == [
        ("POST", "/api/v1/wx/auth/token", None),
        ("GET", "/api/v1/wx/auth/qr/code", "Bearer secret-jwt"),
        ("GET", "/api/v1/wx/auth/qr/image", "Bearer secret-jwt"),
    ]


def test_qr_rejects_non_loopback_image_url() -> None:
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "jwt", "expires_in": 3600})
        return httpx.Response(200, json={
            "code": 0,
            "data": {"code": "https://example.com/qr.png"},
        })

    try:
        _client(handler, password="management-password").start_qr(NOW)
    except WeRSSAuthorizationError as exc:
        assert exc.code == "werss_qr_invalid"
    else:
        raise AssertionError("external QR URL must be rejected")


def test_qr_rejects_unexpected_query_parameters() -> None:
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "jwt", "expires_in": 3600})
        return httpx.Response(200, json={
            "code": 0,
            "data": {"code": "static/wx_qrcode.png?redirect=http://example.com"},
        })

    try:
        _client(handler, password="management-password").start_qr(NOW)
    except WeRSSAuthorizationError as exc:
        assert exc.code == "werss_qr_invalid"
    else:
        raise AssertionError("unexpected QR query parameter must be rejected")


class Repo:
    def __init__(self):
        self.state = None
        self.notices = []

    def get_state(self):
        return self.state

    def upsert_state(self, snapshot):
        self.state = snapshot

    def ensure_notice(self, snapshot, notice_type, recipient_count):
        self.notices.append((snapshot.authorization_version, notice_type, recipient_count))

    def claim_due_notice(self, now):
        return None

    def mark_notice_sent(self, notice_id, now):
        raise AssertionError("not expected")

    def mark_notice_retry(self, notice_id, now, error_code, attempt_count):
        raise AssertionError("not expected")


class Client:
    scan_configured = False

    def __init__(self, state):
        self.state = state

    def fetch_status(self):
        return self.state


class Mailer:
    enabled = True

    def send(self, snapshot, notice_type):
        raise AssertionError("no due notice")


def test_service_uses_absolute_expiry_for_24_hour_boundary_and_notice() -> None:
    repo = Repo()
    client = Client(WeRSSAuthorizationUpstreamState(
        True, "测试公众号", NOW + timedelta(hours=23, minutes=59)
    ))
    service = WeRSSAuthorizationService(
        repo, client, warning_threshold_hours=24,
        mailer=Mailer(), recipient_count=2,
    )

    snapshot = service.monitor_now(NOW)

    assert snapshot.status == "expiring"
    assert repo.notices == [(snapshot.authorization_version, "expiring_24h", 2)]
    assert service.alert(NOW).status == "expiring"


def test_unavailable_refresh_retains_last_good_expiry_without_misclassifying() -> None:
    repo = Repo()
    repo.state = WeRSSAuthorizationSnapshot(
        "valid", "测试公众号", NOW + timedelta(days=2), NOW, NOW, None, "v1"
    )

    class FailedClient(Client):
        def fetch_status(self):
            raise WeRSSAuthorizationError("werss_authorization_timeout")

    service = WeRSSAuthorizationService(repo, FailedClient(None))
    snapshot = service.refresh(NOW + timedelta(minutes=5))

    assert snapshot.status == "unavailable"
    assert snapshot.expires_at == NOW + timedelta(days=2)
    assert snapshot.last_error_code == "werss_authorization_timeout"


def test_service_normalizes_naive_upstream_expiry_to_shanghai() -> None:
    repo = Repo()
    client = Client(
        WeRSSAuthorizationUpstreamState(
            True,
            "测试公众号",
            datetime(2026, 7, 17, 9, 0, 0),
        )
    )
    service = WeRSSAuthorizationService(repo, client)

    snapshot = service.refresh(NOW)

    assert snapshot.status == "expiring"
    assert snapshot.expires_at == datetime(
        2026, 7, 17, 9, 0, 0, tzinfo=ZONE
    )

    first_monitor_snapshot = service.monitor_now(NOW)
    second_snapshot = service.monitor_now(NOW + timedelta(minutes=5))

    assert first_monitor_snapshot is not None
    assert second_snapshot is not None
    assert second_snapshot.status == "expiring"
    assert second_snapshot.expires_at == snapshot.expires_at


def test_alert_normalizes_naive_expiry_loaded_from_database() -> None:
    repo = Repo()
    repo.state = WeRSSAuthorizationSnapshot(
        "unavailable",
        "测试公众号",
        datetime(2026, 7, 17, 9, 0, 0),
        NOW,
        NOW,
        "werss_authorization_timeout",
        "v1",
    )
    service = WeRSSAuthorizationService(repo, Client(None))

    alert = service.alert(NOW)

    assert alert is not None
    assert alert.status == "expiring"
