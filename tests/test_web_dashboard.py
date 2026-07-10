from __future__ import annotations

from pathlib import Path
from typing import Iterator

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
        ),
    )


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def dashboard_service() -> FakeDashboardService:
    return FakeDashboardService()


@pytest.fixture
def app(config: Config, dashboard_service: FakeDashboardService) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        dashboard_service=dashboard_service,
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


def test_dashboard_renders_aggregated_kpis_and_conserving_fallback_table(
    authenticated_client: TestClient,
    dashboard_service: FakeDashboardService,
) -> None:
    response = authenticated_client.get("/dashboard")

    assert response.status_code == 200
    assert dashboard_service.calls == [24]
    for text in ("15", "10", "4 / 5", "18 / 20", "10", "clean", "parse"):
        assert text in response.text
    assert 'data-success="12"' in response.text
    assert 'data-failed="2"' in response.text
    assert 'data-skipped="1"' in response.text
    assert 'data-total="15"' in response.text
    assert "12 + 2 + 1 = 15" in response.text
    for forbidden in (
        "raw_content",
        "wechat_group_msg_raw",
        "article_url",
        "markdown_body",
        "screenshot",
    ):
        assert forbidden not in response.text.lower()


def test_dashboard_has_one_accessible_horizontal_chart_and_text_fallback(
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
    assert "采集结果文本明细" in response.text


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
    assert "0 + 0 + 0 = 0" in response.text
    assert "if (!window.echarts" in response.text
    assert "采集结果图表未加载；上方指标和下方文本表仍可使用。" in response.text


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
    assert calls == ["get_snapshot"]


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
