from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import Config, load_config
from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType
from app.services.auth_service import AuthenticatedAdmin
from app.services.runtime_monitor_service import RuntimeEvent, RunOutsideVisibilityError
from app.storage.collection_event_repo import CollectionEvent
from app.web.app import create_app
from app.web.routes import events


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 12, 30, tzinfo=ZONE)


class FakeAuthService:
    admin = AuthenticatedAdmin(
        id=1, username="admin", using_default_password=False
    )

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None


def _runtime_event() -> RuntimeEvent:
    return RuntimeEvent(
        id=101,
        job_id=7,
        run_id=31,
        target_run_id=51,
        pipeline_type=PipelineType.GROUP,
        worker_id="collector-1",
        level="warning",
        event_type="collection_target_finished",
        stage="target",
        message="safe event",
        metrics_summary='{"failed":1}',
        actor_type="worker",
        actor_name="collector-1",
        create_time=NOW,
    )


class RuntimeService:
    def __init__(self) -> None:
        self.calls = []

    def list_events(self, filters, page, page_size):
        self.calls.append((filters, page, page_size))
        return PagedResult([_runtime_event()], page, page_size, 1)

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))

    def visible_since(self):
        boundary = datetime(2026, 4, 13, 12, 30, tzinfo=ZONE)
        self.calls.append(("visible_since", boundary))
        return boundary

    def to_event_view(self, event):
        from app.services.runtime_monitor_service import RuntimeMonitorService
        return RuntimeMonitorService.to_event_view(self, event)


def _collection_event(event_id=101, message="safe event") -> CollectionEvent:
    return CollectionEvent(
        id=event_id,
        job_id=7,
        run_id=31,
        target_run_id=51,
        level="warning",
        event_type="collection_target_finished",
        stage="target",
        message=message,
        metrics_json='{"failed":1}',
        actor_type="worker",
        actor_name="collector-1",
        create_time=NOW,
    )


class EventRepo:
    def __init__(self, batches=None) -> None:
        self.batches = list(batches or [])
        self.calls = []
        self.in_call = False

    def list_events(self, run_id, after_id, limit, visible_since):
        self.in_call = True
        self.calls.append((run_id, after_id, limit, visible_since))
        result = self.batches.pop(0) if self.batches else []
        self.in_call = False
        return result


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def runtime_service() -> RuntimeService:
    return RuntimeService()


@pytest.fixture
def event_repo() -> EventRepo:
    return EventRepo()


@pytest.fixture
def app(config, runtime_service, event_repo) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        runtime_monitor_service=runtime_service,
        event_repo=event_repo,
    )


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authenticated_client(raw_client: TestClient) -> TestClient:
    raw_client.cookies.set("weinsight_session", "session-token")
    raw_client.cookies.set("weinsight_csrf", "csrf-token")
    return raw_client


def test_events_page_strict_filters_and_safe_output(
    authenticated_client: TestClient,
    runtime_service: RuntimeService,
) -> None:
    response = authenticated_client.get(
        "/events?job_id=7&run_id=31&target_id=51&pipeline=group&"
        "level=warning&start=2026-07-10T11%3A00&end=2026-07-10T12%3A30"
    )

    assert response.status_code == 200
    assert "safe event" in response.text
    assert "运行 #31" in response.text
    for heading in ("时间", "结果摘要", "关联对象", "关键指标", "操作"):
        assert heading in response.text
    assert "WARN · 目标处理完成" in response.text
    assert "<summary>技术详情</summary>" in response.text
    assert "安全消息" in response.text
    assert "仅展示最近 3 个月" in response.text
    filters = runtime_service.calls[-1][0]
    assert filters.target_run_id == 51
    assert filters.pipeline_type is PipelineType.GROUP
    assert filters.start_at.tzinfo is ZONE


@pytest.mark.parametrize(
    "query",
    [
        "unknown=1",
        "run_id=1&run_id=2",
        "target_id=0",
        "pipeline=other",
        "level=fatal",
        "start=2026-07-10T12:00Z",
        "start=2026-07-10T13:00&end=2026-07-10T12:00",
        "page_size=201",
    ],
)
def test_events_page_rejects_invalid_query(
    authenticated_client: TestClient,
    runtime_service: RuntimeService,
    query: str,
) -> None:
    response = authenticated_client.get(f"/events?{query}")

    assert response.status_code == 422
    assert runtime_service.calls == []


def test_events_and_stream_require_authentication(raw_client: TestClient) -> None:
    page = raw_client.get("/events", follow_redirects=False)
    stream = raw_client.get(
        "/events/stream",
        headers={"Accept": "text/event-stream"},
        follow_redirects=False,
    )

    assert page.status_code == 303
    assert stream.status_code == 401


def test_events_page_service_call_runs_in_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def recording(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(events, "run_in_threadpool", recording)

    assert authenticated_client.get("/events").status_code == 200
    assert calls == ["list_events"]


def _request(
    *,
    app: FastAPI,
    query: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    disconnected: bool = False,
) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if disconnected or sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/events/stream",
            "raw_path": b"/events/stream",
            "query_string": query,
            "headers": headers or [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "app": app,
        },
        receive,
    )


def test_sse_response_headers_and_last_event_id_precedence(
    app: FastAPI, runtime_service: RuntimeService
) -> None:
    request = _request(
        app=app,
        query=b"run_id=31&after_id=2",
        headers=[(b"last-event-id", b"100")],
    )

    response = asyncio.run(events.event_stream(request))

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.body_iterator.after_id == 100
    assert response.body_iterator.run_id == 31
    assert runtime_service.calls == [("get_run", 31), ("visible_since", datetime(2026, 4, 13, 12, 30, tzinfo=ZONE))]


def test_sse_expired_run_is_rejected_before_stream_creation(app: FastAPI, runtime_service: RuntimeService) -> None:
    def expired(run_id):
        raise RunOutsideVisibilityError("expired")
    runtime_service.get_run = expired
    with pytest.raises(HTTPException) as caught:
        asyncio.run(events.event_stream(_request(app=app, query=b"run_id=31")))
    assert caught.value.status_code == 404
    assert caught.value.detail == "该记录已超出可查看范围"


@pytest.mark.parametrize(
    ("query", "header"),
    [
        (b"unknown=1", None),
        (b"run_id=0", None),
        (b"after_id=-1", None),
        (b"after_id=1&after_id=2", None),
        (b"", b"+1"),
        (b"", b" 1"),
        (b"", b"1.0"),
    ],
)
def test_sse_rejects_noncanonical_cursor_or_query(
    app: FastAPI, query: bytes, header: bytes | None
) -> None:
    headers = [] if header is None else [(b"last-event-id", header)]

    with pytest.raises(ValueError):
        events._stream_parameters(_request(app=app, query=query, headers=headers))


def test_sse_resumes_caps_batch_and_does_not_hold_connection_across_yield(
    app: FastAPI,
) -> None:
    repo = EventRepo([[_collection_event(101, "<b>13812345678</b> https://x/y")]])
    request = _request(app=app)
    stream = events.CollectionEventStream(
        request=request,
        event_repo=repo,
        run_id=31,
        after_id=100,
        visible_since=datetime(2026, 4, 13, 12, 30, tzinfo=ZONE),
        max_polls=1,
        poll_seconds=0,
    )

    async def consume():
        chunks = []
        async for chunk in stream:
            assert repo.in_call is False
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume())
    payload = "".join(chunks)

    assert repo.calls == [(31, 100, 200, datetime(2026, 4, 13, 12, 30, tzinfo=ZONE))]
    assert "id: 101\n" in payload
    assert "event: collection\n" in payload
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    decoded = json.loads(data_line.removeprefix("data: "))
    assert decoded["level"] == "WARNING"
    assert decoded["summary"] == "WARN · 目标处理完成"
    assert "13812345678" not in decoded["message"]
    assert "https://" not in decoded["message"]
    assert "\n" not in data_line


def test_sse_seeded_after_initial_history_appends_only_new_event(
    app: FastAPI,
) -> None:
    repo = EventRepo([[_collection_event(104, "new event")]])
    stream = events.CollectionEventStream(
        request=_request(app=app),
        event_repo=repo,
        run_id=31,
        after_id=103,
        visible_since=datetime(2026, 4, 13, 12, 30, tzinfo=ZONE),
        max_polls=1,
        poll_seconds=0,
    )

    async def consume():
        return "".join([chunk async for chunk in stream])

    payload = asyncio.run(consume())

    assert repo.calls == [(31, 103, 200, datetime(2026, 4, 13, 12, 30, tzinfo=ZONE))]
    assert "id: 104\n" in payload
    for initial_id in (101, 102, 103):
        assert f"id: {initial_id}\n" not in payload


def test_sse_keepalive_disconnect_and_cancellation(app: FastAPI) -> None:
    repo = EventRepo([[], []])
    request = _request(app=app)
    ticks = iter([0.0, 15.0, 15.0])
    stream = events.CollectionEventStream(
        request=request,
        event_repo=repo,
        run_id=None,
        after_id=None,
        visible_since=datetime(2026, 4, 13, 12, 30, tzinfo=ZONE),
        max_polls=2,
        poll_seconds=0,
        keepalive_seconds=15,
        monotonic=lambda: next(ticks),
        sleeper=lambda delay: asyncio.sleep(0),
    )

    async def first_chunk():
        async for chunk in stream:
            return chunk

    assert asyncio.run(first_chunk()) == ": keepalive\n\n"

    disconnected_stream = events.CollectionEventStream(
        request=_request(app=app, disconnected=True),
        event_repo=EventRepo([[_collection_event()]]),
        run_id=None,
        after_id=None,
        visible_since=datetime(2026, 4, 13, 12, 30, tzinfo=ZONE),
        max_polls=1,
        poll_seconds=0,
    )

    async def disconnected_chunks():
        return [chunk async for chunk in disconnected_stream]

    assert asyncio.run(disconnected_chunks()) == []

    async def cancelled_sleep(delay):
        raise asyncio.CancelledError

    cancelled_stream = events.CollectionEventStream(
        request=_request(app=app),
        event_repo=EventRepo([[]]),
        run_id=None,
        after_id=None,
        visible_since=datetime(2026, 4, 13, 12, 30, tzinfo=ZONE),
        max_polls=None,
        poll_seconds=1,
        sleeper=cancelled_sleep,
    )

    async def cancel():
        async for _ in cancelled_stream:
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancel())


def test_sse_recursively_sanitizes_and_bounds_metrics_json() -> None:
    event = _collection_event()
    event = CollectionEvent(
        **{
            **{field: getattr(event, field) for field in event.__dataclass_fields__},
            "metrics_json": json.dumps(
                {
                    "html": "<b>secret</b>",
                    "url": "https://example.com/private",
                    "control": "line1\nline2\u0000",
                    "deep": {"a": {"b": {"c": "too deep"}}},
                    "many": list(range(100)),
                    "long": "x" * 2000,
                }
            ),
        }
    )

    payload = events._format_sse_event(event)
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    decoded = json.loads(data_line.removeprefix("data: "))
    metrics = decoded["metrics"]
    encoded = json.dumps(metrics, ensure_ascii=False)

    assert "<b>" not in encoded
    assert "https://" not in encoded
    assert "\u0000" not in encoded
    assert "line1\nline2" not in encoded
    assert len(metrics["many"]) <= 21
    assert len(metrics["long"]) <= 200
    assert len(encoded.encode("utf-8")) <= 4096
