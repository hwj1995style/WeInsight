from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType, RunStatus
from app.rpa.desktop_probe import WechatHealthStatus
from app.services.auth_service import AuthenticatedAdmin
from app.services.runtime_monitor_service import (
    JobRuntimeHistory,
    RunDetail,
    RunDeletionNotAllowedError,
    RunDeletionResult,
    RunNotFoundError,
    RunOutsideVisibilityError,
    RunSummary,
    RuntimeDashboardSnapshot,
    RuntimeEvent,
    RunTrendBucket,
    TargetRunDetail,
    TodayRunCounts,
    UiLockView,
    WechatHealthView,
    WorkerHeartbeatView,
    WorkerMonitorSnapshot,
)
from app.web.app import create_app


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 12, 30, tzinfo=ZONE)


class FakeAuthService:
    admin = AuthenticatedAdmin(
        id=1, username="admin", using_default_password=False
    )

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None

    def verify_csrf(self, session_token, csrf_token, now):
        return session_token == "session-token" and csrf_token == "csrf-token"


def _run() -> RunSummary:
    return RunSummary(
        id=31,
        job_id=7,
        job_name="晨间群采集",
        pipeline_type=PipelineType.GROUP,
        scheduled_at=NOW - timedelta(minutes=5),
        status=RunStatus.FAILED,
        worker_id="collector-1",
        start_time=NOW - timedelta(minutes=5),
        end_time=NOW - timedelta(minutes=4),
        target_total_count=1,
        target_success_count=0,
        target_failed_count=1,
    )


def _event(event_id: int = 101) -> RuntimeEvent:
    return RuntimeEvent(
        id=event_id,
        job_id=7,
        run_id=31,
        target_run_id=51,
        pipeline_type=PipelineType.GROUP,
        worker_id="collector-1",
        level="error",
        event_type="collection_target_finished",
        stage="target",
        message="target failed",
        metrics_summary='{"failed":1}',
        actor_type="worker",
        actor_name="collector-1",
        create_time=NOW,
    )


class FakeRuntimeMonitorService:
    def __init__(self, screenshot_path: str = "截图路径无效") -> None:
        self.calls = []
        self.delete_error = None
        self.run_page = PagedResult([_run()], 1, 20, 1)
        self.event_page = PagedResult([_event()], 1, 50, 1)
        target = TargetRunDetail(
            id=51,
            job_target_id=9,
            target_name="核心群A",
            status="failed",
            stage="copy",
            batch_id="group-31-9",
            read_count=4,
            insert_count=1,
            duplicate_count=2,
            skipped_count=1,
            error_code="WECHAT_RPA_ERROR",
            error_summary="safe failure",
            screenshot_path=screenshot_path,
            start_time=NOW - timedelta(minutes=5),
            end_time=NOW - timedelta(minutes=4),
        )
        self.detail = RunDetail(
            run=_run(),
            hostname="COLLECTOR-01",
            lease_expires_at=NOW,
            error_code="RUN_FAILED",
            error_summary="safe run failure",
            targets=(target,),
        )
        self.workers = WorkerMonitorSnapshot(
            workers=(
                WorkerHeartbeatView(
                    "collector-1",
                    "collector",
                    "COLLECTOR-01",
                    123,
                    "v1",
                    "running",
                    NOW,
                    NOW - timedelta(hours=1),
                    None,
                    True,
                ),
            ),
            health_checks=(
                WechatHealthView(
                    "COLLECTOR-01",
                    WechatHealthStatus.OK,
                    "4.1.8.107",
                    0,
                    "WeChat healthy",
                    NOW,
                ),
            ),
            ui_lock=UiLockView(
                "live",
                "group",
                "group-31-9",
                NOW - timedelta(seconds=5),
                NOW,
                NOW + timedelta(seconds=30),
            ),
            checked_at=NOW,
        )
        self.dashboard = RuntimeDashboardSnapshot(
            live_collector_count=1,
            total_worker_count=1,
            workers=self.workers.workers,
            latest_wechat_status=WechatHealthStatus.OK,
            latest_wechat_checked_at=NOW,
            ui_lock_state="live",
            active_job_count=2,
            stop_requested_job_count=1,
            today_runs=TodayRunCounts(running=1, success=3, failed=1),
            trend=tuple(
                RunTrendBucket(
                    NOW.replace(minute=0, second=0, microsecond=0)
                    - timedelta(hours=23 - index),
                    1 if index == 23 else 0,
                    1 if index == 23 else 0,
                    1 if index == 23 else 0,
                    1 if index == 23 else 0,
                    1 if index == 23 else 0,
                )
                for index in range(24)
            ),
            generated_at=NOW,
        )

    def list_runs(self, filters, page, page_size):
        self.calls.append(("list_runs", filters, page, page_size))
        return self.run_page

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return self.detail

    def list_events(self, filters, page, page_size):
        self.calls.append(("list_events", filters, page, page_size))
        return self.event_page

    def to_event_view(self, event):
        from app.services.runtime_monitor_service import RuntimeMonitorService
        return RuntimeMonitorService.to_event_view(self, event)

    def get_workers(self, now):
        self.calls.append(("get_workers", now))
        return self.workers

    def get_dashboard(self, now):
        self.calls.append(("get_dashboard", now))
        return self.dashboard

    def get_job_history(self, job_id, limit=10):
        self.calls.append(("get_job_history", job_id, limit))
        return JobRuntimeHistory((_run(),), (_event(),))

    def delete_terminal_run(self, run_id, actor, now):
        self.calls.append(("delete_terminal_run", run_id, actor, now))
        if self.delete_error is not None:
            raise self.delete_error
        status = self.detail.run.status
        self.detail = None
        return RunDeletionResult(run_id, 7, status, 1, 1)


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def runtime_service() -> FakeRuntimeMonitorService:
    return FakeRuntimeMonitorService()


@pytest.fixture
def app(
    config: Config,
    runtime_service: FakeRuntimeMonitorService,
) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        runtime_monitor_service=runtime_service,
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


def test_runs_list_strict_filters_and_pagination(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    response = authenticated_client.get(
        "/runs?pipeline=group&status=failed&date=2026-07-10&"
        "job_id=7&name=%E6%99%A8%E9%97%B4&page=1&page_size=20"
    )

    assert response.status_code == 200
    assert "晨间群采集" in response.text
    assert "查看运行" in response.text
    assert "仅展示最近 3 个月" in response.text
    call = runtime_service.calls[-1]
    assert call[0] == "list_runs"
    assert call[1].pipeline_type is PipelineType.GROUP
    assert call[1].status is RunStatus.FAILED
    assert call[1].job_id == 7


@pytest.mark.parametrize(
    "query",
    [
        "unknown=1",
        "pipeline=group&pipeline=article",
        "status=active",
        "date=2026-7-10",
        "job_id=0",
        "page=0",
        "page_size=101",
    ],
)
def test_runs_reject_invalid_query_without_service_call(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
    query: str,
) -> None:
    response = authenticated_client.get(f"/runs?{query}")

    assert response.status_code == 422
    assert runtime_service.calls == []


def test_run_detail_shows_local_path_as_text_only(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    root = Path("runtime/screenshots").resolve()
    runtime_service.detail = replace(
        runtime_service.detail,
        targets=(
            replace(
                runtime_service.detail.targets[0],
                screenshot_path=str(root / "group" / "failure.png"),
            ),
        ),
    )

    response = authenticated_client.get("/runs/31")

    assert response.status_code == 200
    assert "COLLECTOR-01" in response.text
    assert str(root) in response.text
    assert "<img" not in response.text.lower()
    assert "download=" not in response.text.lower()
    assert "file://" not in response.text.lower()
    assert "最近事件" in response.text
    assert "ERROR · 目标处理完成" in response.text
    assert 'id="target-51"' in response.text


def test_terminal_run_detail_shows_physical_delete_action(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/runs/31")

    assert response.status_code == 200
    assert 'action="/runs/31/delete"' in response.text
    assert "删除运行实例" in response.text
    assert "采集结果和采集日志仍会保留" in response.text


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
def test_nonterminal_run_detail_hides_delete_action(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
    status: RunStatus,
) -> None:
    runtime_service.detail = replace(
        runtime_service.detail,
        run=replace(runtime_service.detail.run, status=status),
    )

    response = authenticated_client.get("/runs/31")

    assert response.status_code == 200
    assert 'action="/runs/31/delete"' not in response.text
    assert "删除运行实例" not in response.text


def test_delete_terminal_run_redirects_to_list(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    response = authenticated_client.post(
        "/runs/31/delete",
        data={"csrf_token": "csrf-token", "confirm_delete": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/runs"
    call = runtime_service.calls[-1]
    assert call[:3] == ("delete_terminal_run", 31, "admin")
    assert call[3].tzinfo is not None


@pytest.mark.parametrize(
    "data",
    [
        {"csrf_token": "csrf-token", "confirm_delete": "0"},
        {"csrf_token": "csrf-token"},
        {
            "csrf_token": "csrf-token",
            "confirm_delete": "1",
            "unknown": "x",
        },
    ],
)
def test_delete_run_rejects_invalid_form_without_service_call(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
    data,
) -> None:
    response = authenticated_client.post("/runs/31/delete", data=data)

    assert response.status_code == 422
    assert "请检查删除参数" in response.text
    assert not any(call[0] == "delete_terminal_run" for call in runtime_service.calls)


def test_delete_nonterminal_run_returns_refreshed_409(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    runtime_service.detail = replace(
        runtime_service.detail,
        run=replace(runtime_service.detail.run, status=RunStatus.RUNNING),
    )
    runtime_service.delete_error = RunDeletionNotAllowedError(RunStatus.RUNNING)

    response = authenticated_client.post(
        "/runs/31/delete",
        data={"csrf_token": "csrf-token", "confirm_delete": "1"},
    )

    assert response.status_code == 409
    assert "当前运行状态不允许删除" in response.text
    assert "运行中" in response.text
    assert 'action="/runs/31/delete"' not in response.text


def test_delete_missing_run_returns_safe_404(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    runtime_service.delete_error = RunNotFoundError("secret internal detail")

    response = authenticated_client.post(
        "/runs/31/delete",
        data={"csrf_token": "csrf-token", "confirm_delete": "1"},
    )

    assert response.status_code == 404
    assert "运行实例不存在" in response.text
    assert "secret internal detail" not in response.text


def test_delete_run_does_not_accept_get(authenticated_client: TestClient) -> None:
    assert authenticated_client.get("/runs/31/delete").status_code == 405


def test_delete_run_requires_authentication(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/runs/31/delete",
        data={"csrf_token": "csrf-token", "confirm_delete": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_delete_run_rejects_invalid_csrf(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    response = authenticated_client.post(
        "/runs/31/delete",
        data={"csrf_token": "wrong-token", "confirm_delete": "1"},
    )

    assert response.status_code == 403
    assert not any(call[0] == "delete_terminal_run" for call in runtime_service.calls)


def test_article_run_detail_shows_rss_metrics_without_rpa_presentation(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    runtime_service.detail = replace(
        runtime_service.detail,
        run=replace(runtime_service.detail.run, pipeline_type=PipelineType.ARTICLE),
        targets=(
            replace(
                runtime_service.detail.targets[0],
                http_status=200,
                feed_item_count=12,
                insert_count=7,
                duplicate_count=3,
                invalid_count=2,
                elapsed_ms=456,
            ),
        ),
    )

    html = authenticated_client.get("/runs/31").text

    for value in ("HTTP 状态", "Feed 条目", "新增", "重复", "无效", "耗时", "456 ms"):
        assert value in html
    for value in ("状态 / 阶段", "本机截图路径", "UI 锁等待", "路由阶段"):
        assert value not in html


def test_run_detail_help_text_is_pipeline_specific(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    group_html = authenticated_client.get("/runs/31").text
    runtime_service.detail = replace(
        runtime_service.detail,
        run=replace(runtime_service.detail.run, pipeline_type=PipelineType.ARTICLE),
    )
    article_html = authenticated_client.get("/runs/31").text

    group_help = "读取、新增、重复与跳过均来自目标运行记录。"
    rss_help = "采集统计来自目标运行及对应 RSS 采集日志。"
    assert group_help in group_html
    assert rss_help not in group_html
    assert rss_help in article_html
    assert group_help not in article_html


def test_run_detail_orders_latest_history_ascending_and_seeds_sse_cursor(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    runtime_service.event_page = PagedResult(
        [_event(103), _event(102), _event(101)],
        1,
        50,
        103,
    )

    response = authenticated_client.get("/runs/31")

    positions = [
        response.text.index(f'data-event-id="{event_id}"')
        for event_id in (101, 102, 103)
    ]
    assert positions == sorted(positions)
    assert "new EventSource('/events/stream?run_id=31&after_id=103')" in response.text


def test_run_detail_without_initial_events_omits_sse_cursor(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    runtime_service.event_page = PagedResult([], 1, 50, 0)

    response = authenticated_client.get("/runs/31")

    assert "new EventSource('/events/stream?run_id=31')" in response.text
    assert "after_id=" not in response.text


def test_expired_run_detail_has_distinct_404_and_skips_events(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeMonitorService,
) -> None:
    def expired(run_id):
        runtime_service.calls.append(("get_run", run_id))
        raise RunOutsideVisibilityError("expired run: 31")

    runtime_service.get_run = expired
    response = authenticated_client.get("/runs/31")
    assert response.status_code == 404
    assert "该记录已超出可查看范围" in response.text
    assert "运行实例不存在" not in response.text
    assert [call[0] for call in runtime_service.calls] == ["get_run"]


def test_run_detail_invalid_path_never_echoes_original(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/runs/31")

    assert "截图路径无效" in response.text
    assert "outside" not in response.text


def test_workers_page_redirects_to_dashboard_worker_cards(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/workers", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard#worker-status"


def test_runtime_pages_require_authentication(raw_client: TestClient) -> None:
    for path in ("/runs", "/runs/31", "/workers"):
        response = raw_client.get(path, follow_redirects=False)
        assert response.status_code == 303


def test_runtime_service_calls_use_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.web.routes import runs

    calls = []

    async def recording(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(runs, "run_in_threadpool", recording)

    assert authenticated_client.get("/runs").status_code == 200
    assert authenticated_client.get("/runs/31").status_code == 200
    assert calls == ["list_runs", "get_run", "list_events"]


def test_navigation_has_runtime_links_and_remains_scrollable(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/runs")

    for path in ("/runs", "/events"):
        assert f'href="{path}"' in response.text
    assert 'href="/workers"' not in response.text
    css = Path("app/web/static/app.css").read_text(encoding="utf-8")
    assert ".primary-nav" in css and "overflow-x: auto" in css
