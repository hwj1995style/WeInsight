from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.services.auth_service import AuthenticatedAdmin
from app.services.dashboard_service import (
    BacklogCount,
    CollectionOutcomeCounts,
    DashboardSnapshot,
)
from app.rpa.desktop_probe import WechatHealthStatus
from app.services.runtime_monitor_service import (
    RunTrendBucket,
    RuntimeDashboardSnapshot,
    TodayRunCounts,
    WorkerHeartbeatView,
)
from app.storage import dashboard_repo
from app.storage.dashboard_repo import MysqlDashboardRepo
from app.web.app import create_app
from app.web.routes import dashboard as dashboard_routes


class FakeAuthService:
    admin = AuthenticatedAdmin(id=1, username="admin", using_default_password=False)

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None


class FakeDashboardService:
    def __init__(self, snapshot: DashboardSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls: list[int] = []

    def get_snapshot(self, hours: int = 24) -> DashboardSnapshot:
        self.calls.append(hours)
        return self.snapshot


class FakeRuntimeDashboardService:
    def __init__(self) -> None:
        self.calls = []
        current = datetime(2026, 7, 10, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.snapshot = RuntimeDashboardSnapshot(
            live_collector_count=1,
            total_worker_count=2,
            workers=(
                WorkerHeartbeatView(
                    "pipeline-current", "pipeline", "HOST-A", 101,
                    "pipeline-worker-v1", "running", current,
                    current - timedelta(hours=1), "safe pipeline error", True,
                ),
                WorkerHeartbeatView(
                    "collector-current", "collector", "HOST-A", 102,
                    "managed-collector-v1", "running", current,
                    current - timedelta(hours=2), None, True,
                ),
            ),
            latest_wechat_status=WechatHealthStatus.OK,
            latest_wechat_checked_at=current,
            ui_lock_state="live",
            active_job_count=3,
            stop_requested_job_count=1,
            today_runs=TodayRunCounts(
                queued=1,
                running=2,
                success=5,
                partial_success=1,
                failed=2,
                cancelled=1,
                aborted=1,
            ),
            trend=tuple(
                RunTrendBucket(
                    current - timedelta(hours=23 - index),
                    success_count=(2 if index == 23 else 0),
                    partial_success_count=(1 if index == 23 else 0),
                    failed_count=(1 if index == 23 else 0),
                    cancelled_count=(1 if index == 23 else 0),
                    aborted_count=(1 if index == 23 else 0),
                )
                for index in range(24)
            ),
            generated_at=current,
        )

    def get_dashboard(self, now):
        self.calls.append(now)
        return self.snapshot


def _snapshot(*, zero: bool = False) -> DashboardSnapshot:
    if zero:
        return DashboardSnapshot.empty(window_hours=24)
    return DashboardSnapshot(
        window_hours=24,
        group_collection=CollectionOutcomeCounts(
            success=12, failed=2, skipped=1, total=15
        ),
        article_collection=CollectionOutcomeCounts(
            success=7, failed=1, skipped=2, total=10
        ),
        group_config_total=5,
        group_config_enabled=4,
        article_config_total=20,
        article_config_enabled=18,
        group_daily_report_count=4,
        article_daily_report_count=6,
        backlogs=(
            BacklogCount("group", "clean", "pending", 3),
            BacklogCount("article", "parse", "failed", 1),
            BacklogCount("report", "report_generation", "running", 2),
        ),
    )


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def dashboard_service() -> FakeDashboardService:
    return FakeDashboardService()


@pytest.fixture
def runtime_service() -> FakeRuntimeDashboardService:
    return FakeRuntimeDashboardService()


@pytest.fixture
def app(
    config: Config,
    dashboard_service: FakeDashboardService,
    runtime_service: FakeRuntimeDashboardService,
) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        dashboard_service=dashboard_service,
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


def test_dashboard_renders_grouped_overview_cards_without_duplicate_tables(
    authenticated_client: TestClient,
    dashboard_service: FakeDashboardService,
) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert dashboard_service.calls == [24]
    for text in (
        "15", "10", "4 / 5", "18 / 20", "10", "clean", "parse",
        "日报", "report_generation",
    ):
        assert text in response.text
    assert response.text.count('<article class="overview-card ') == 2
    assert response.text.count('class="overview-card-group') == 3
    for heading in ("系统运行", "任务运行", "采集结果", "配置与产出"):
        assert heading in response.text
    assert "逐小时运行终态守恒表" not in response.text
    assert "采集结果文本明细" not in response.text
    for forbidden in (
        "raw_content",
        "wechat_group_msg_raw",
        "article_url",
        "markdown_body",
        "screenshot",
    ):
        assert forbidden not in response.text.lower()


def test_dashboard_uses_direction_a_layout(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    for class_name in (
        "dashboard-overview-grid",
        "overview-card",
        "overview-metric-grid",
        "overview-system-grid",
        "overview-business-grid",
        "dashboard-chart-grid",
        "dashboard-backlog",
    ):
        assert class_name in response.text
    assert "管理控制台" not in response.text


def test_dashboard_renders_latest_workers_as_cards_with_error_dialog(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert 'id="worker-status"' in response.text
    assert response.text.count('<section class="overview-worker ') == 2
    assert 'class="worker-status-section"' not in response.text
    assert 'class="worker-status-card' not in response.text
    assert "Pipeline" in response.text
    assert "Collector" in response.text
    assert "最近心跳" in response.text
    assert "启动时间" in response.text
    assert "无当前错误" in response.text
    assert "查看错误" in response.text
    assert "safe pipeline error" in response.text
    assert '<dialog class="worker-error-dialog"' in response.text
    assert 'href="/workers"' not in response.text


def test_dashboard_keeps_missing_worker_type_visible(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeDashboardService,
) -> None:
    runtime_service.snapshot = replace(
        runtime_service.snapshot,
        workers=tuple(
            worker
            for worker in runtime_service.snapshot.workers
            if worker.worker_type == "collector"
        ),
    )

    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert "Pipeline" in response.text
    assert "未注册" in response.text


def test_dashboard_uses_direction_a_echarts_theme(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/dashboard")

    for color in ("#16855b", "#c23838", "#8b98aa", "#1769d2", "#e6ebf2", "#68758a"):
        assert color in response.text
    assert "animation: false" in response.text


def test_dashboard_has_one_accessible_horizontal_chart_without_duplicate_table(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.text.count('id="collection-chart"') == 1
    assert 'role="img"' in response.text
    assert 'aria-label="最近 24 小时采集结果构成' in response.text
    assert "type: 'value'" in response.text
    assert "type: 'category'" in response.text
    assert "show: true" in response.text
    assert "animation: false" in response.text
    assert "window.addEventListener('resize'" in response.text
    assert "采集结果文本明细" not in response.text


def test_dashboard_renders_grouped_runtime_metrics_and_24_hour_trend(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeDashboardService,
) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert len(runtime_service.calls) == 1
    for text in ("Pipeline", "Collector", "微信状态", "正常", "UI 锁", "运行中 2", "停止中 1"):
        assert text in response.text
    assert "2 / 2" not in response.text
    assert ">ok<" not in response.text
    assert "查看 Worker 状态" not in response.text
    assert 'href="#worker-status"' not in response.text
    assert response.text.count('id="run-trend-chart"') == 1
    assert "24 小时运行终态趋势" in response.text
    assert "逐小时运行终态守恒表" not in response.text
    assert "运行中" not in response.text.split(
        'id="run-trend-chart-data"', 1
    )[-1].split("</script>", 1)[0]


def test_dashboard_does_not_report_unavailable_ui_lock_as_free(
    authenticated_client: TestClient,
    runtime_service: FakeRuntimeDashboardService,
) -> None:
    runtime_service.snapshot = replace(
        runtime_service.snapshot,
        ui_lock_state="unavailable",
    )

    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert "最小权限下不可用" in response.text
    assert "不代表 UI 锁空闲" in response.text


def test_dashboard_loads_only_local_echarts_and_other_pages_do_not(
    authenticated_client: TestClient,
) -> None:
    dashboard = authenticated_client.get("/dashboard")
    results = authenticated_client.get("/results/groups")

    assert 'src="/static/vendor/echarts.min.js"' in dashboard.text
    assert "htmx.min.js" not in dashboard.text
    assert "cdn.jsdelivr" not in dashboard.text
    assert "unpkg.com" not in dashboard.text
    assert "echarts.min.js" not in results.text


def test_dashboard_zero_data_is_safe_and_kpis_survive_chart_failure(
    authenticated_client: TestClient,
    dashboard_service: FakeDashboardService,
) -> None:
    dashboard_service.snapshot = _snapshot(zero=True)

    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert "当前没有待处理任务" in response.text
    assert "if (!window.echarts" in response.text
    assert "采集结果图表未加载；请稍后刷新。" in response.text


def test_dashboard_requires_authentication(raw_client: TestClient) -> None:
    response = raw_client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_service_call_runs_in_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(
        dashboard_routes, "run_in_threadpool", recording_threadpool
    )

    assert authenticated_client.get("/dashboard").status_code == 200
    assert calls == ["get_snapshot", "get_dashboard"]


def test_dashboard_sql_uses_only_aggregates_and_safe_control_tables() -> None:
    statements = (
        dashboard_repo._group_collection_statement(),
        dashboard_repo._article_collection_statement(),
        dashboard_repo._config_count_statement(),
        dashboard_repo._report_count_statement(),
        dashboard_repo._backlog_statement(),
    )
    sql = "\n".join(str(statement).lower() for statement in statements)

    for required in (
        "wechat_group_collect_log",
        "wechat_article_collect_log",
        "wechat_group_config",
        "wechat_public_account_config",
        "wechat_group_daily_report",
        "wechat_article_daily_report",
        "wechat_group_process_task",
        "wechat_article_process_task",
        "wechat_report_generation_request",
        "count(",
    ):
        assert required in sql
    for forbidden in (
        "wechat_group_msg_raw",
        "clean_content",
        "markdown_body",
        "article_url",
        "content_html",
        "error_msg",
        "screenshot_path",
    ):
        assert forbidden not in sql
    assert "task_type <> 'article_daily_report'" in sql
    assert "'report_generation'" in sql


@pytest.mark.parametrize(
    "statement_factory",
    (
        dashboard_repo._group_collection_statement,
        dashboard_repo._article_collection_statement,
    ),
)
def test_dashboard_collection_sql_counts_only_explicit_terminal_statuses(
    statement_factory,
) -> None:
    _assert_terminal_status_contract(str(statement_factory()))


def test_terminal_projection_excludes_unknown_and_running_from_skipped_and_total() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE collect_log (status TEXT NOT NULL)")
    connection.executemany(
        "INSERT INTO collect_log (status) VALUES (?)",
        [
            ("success",),
            ("failed",),
            ("skipped",),
            ("interrupted",),
            ("unknown",),
            ("running",),
        ],
    )

    row = connection.execute(
        f"SELECT {dashboard_repo._terminal_outcome_projection()} FROM collect_log"
    ).fetchone()

    assert row == (1, 1, 2, 4)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda sql: sql.replace(
            "status IN ('skipped', 'interrupted')",
            "status NOT IN ('success', 'failed')",
        ),
        lambda sql: sql.replace(
            "COALESCE(SUM(CASE WHEN status IN ('success', 'failed', 'skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS total_count",
            "COUNT(*) AS total_count",
        ),
    ),
)
def test_terminal_status_contract_rejects_broad_bucket_mutations(mutation) -> None:
    canonical = """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
            COALESCE(SUM(CASE WHEN status IN ('skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS skipped_count,
            COALESCE(SUM(CASE WHEN status IN ('success', 'failed', 'skipped', 'interrupted') THEN 1 ELSE 0 END), 0) AS total_count
    """

    with pytest.raises(AssertionError):
        _assert_terminal_status_contract(mutation(canonical))


def _assert_terminal_status_contract(sql: str) -> None:
    normalized = " ".join(sql.split())
    assert "status NOT IN" not in normalized
    assert (
        "status IN ('skipped', 'interrupted') THEN 1 ELSE 0 END" in normalized
    )
    assert "COUNT(*) AS total_count" not in normalized
    assert (
        "status IN ('success', 'failed', 'skipped', 'interrupted') "
        "THEN 1 ELSE 0 END), 0) AS total_count" in normalized
    )


def test_dashboard_outcome_counts_reject_non_conserving_data() -> None:
    with pytest.raises(ValueError, match="must equal total"):
        CollectionOutcomeCounts(success=3, failed=1, skipped=0, total=5)


def test_create_app_default_data_services_share_one_engine(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    monkeypatch.setitem(
        create_app.__globals__, "create_mysql_engine", lambda mysql: engine
    )

    app = create_app(config)

    assert app.state.result_service.repo.engine is engine
    assert app.state.group_report_service.repo.engine is engine
    assert app.state.article_report_service.repo.engine is engine
    assert app.state.summary_report_service.repo.engine is engine
    assert app.state.dashboard_service.repo.engine is engine
    assert app.state.runtime_monitor_service.repo.engine is engine
    assert app.state.event_repo.engine is engine


class DashboardResult:
    def __init__(self, *, one=None, rows=None) -> None:
        self.one_row = one
        self.rows = rows

    def mappings(self):
        return self

    def one(self):
        return self.one_row

    def all(self):
        return self.rows


class DashboardConnection:
    def __init__(self) -> None:
        self.results = iter(
            (
                DashboardResult(
                    one={
                        "success_count": 2,
                        "failed_count": 1,
                        "skipped_count": 1,
                        "total_count": 4,
                    }
                ),
                DashboardResult(
                    one={
                        "success_count": 3,
                        "failed_count": 0,
                        "skipped_count": 2,
                        "total_count": 5,
                    }
                ),
                DashboardResult(
                    one={
                        "group_total": 5,
                        "group_enabled": 4,
                        "article_total": 20,
                        "article_enabled": 18,
                    }
                ),
                DashboardResult(
                    one={"group_report_count": 2, "article_report_count": 3}
                ),
                DashboardResult(
                    rows=[
                        {
                            "pipeline": "group",
                            "task_type": "clean",
                            "status": "pending",
                            "count": 7,
                        }
                    ]
                ),
            )
        )

    def execute(self, statement, params=None):
        return next(self.results)


class DashboardEngine:
    def begin(self):
        connection = DashboardConnection()

        class Context:
            def __enter__(self):
                return connection

            def __exit__(self, *args):
                return False

        return Context()


def test_dashboard_repo_maps_only_aggregate_rows_into_conserving_snapshot() -> None:
    snapshot = MysqlDashboardRepo(DashboardEngine()).get_snapshot(24)

    assert snapshot.group_collection == CollectionOutcomeCounts(2, 1, 1, 4)
    assert snapshot.article_collection == CollectionOutcomeCounts(3, 0, 2, 5)
    assert snapshot.group_config_enabled == 4
    assert snapshot.article_config_total == 20
    assert snapshot.daily_report_count == 5
    assert snapshot.backlog_count == 7
