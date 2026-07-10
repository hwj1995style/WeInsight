from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import JobStatus, PipelineType, ScheduleSpec
from app.services.auth_service import AuthenticatedAdmin
from app.services.collection_job_service import (
    CollectionJobDetail,
    CollectionJobSummary,
    JobMixedPipelineError,
    JobNotFoundError,
    JobOverlapError,
    JobStateTransitionError,
    JobTargetDisabledError,
    JobTargetNotFoundError,
    JobValidationError,
    JobVersionConflictError,
)
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.storage.group_repo import GroupConfigRecord
from app.web.app import create_app


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 0, tzinfo=ZONE)


class FakeAuthService:
    def __init__(self) -> None:
        self.admin = AuthenticatedAdmin(
            id=1,
            username="admin",
            using_default_password=True,
        )

    def authenticate(self, session_token, csrf_token, now):
        if session_token != "session-token":
            return None
        if csrf_token is not None and csrf_token != "csrf-token":
            return None
        return self.admin

    def verify_csrf(self, session_token, csrf_token, now):
        return session_token == "session-token" and csrf_token == "csrf-token"


class FakeSourceService:
    def __init__(self) -> None:
        self.groups = (
            GroupConfigRecord(
                id=7,
                group_name="核心群A",
                priority=1,
                poll_interval_seconds=30,
                enabled=True,
                is_core_group=True,
                backtrack_pages=1,
                extra_backtrack_pages=3,
            ),
        )
        self.articles = (
            ArticleAccountConfigRecord(
                id=9,
                account_name="行业观察",
                account_type="subscription",
                priority=2,
                poll_interval_minutes=10,
                daily_window_start="07:30:00",
                daily_window_end="19:30:00",
                max_articles_per_round=5,
                enabled=True,
            ),
        )
        self.calls: list[tuple[str, int]] = []

    def list_enabled_groups_for_job(self, limit=100):
        self.calls.append(("list_enabled_groups_for_job", limit))
        return self.groups

    def list_enabled_articles_for_job(self, limit=100):
        self.calls.append(("list_enabled_articles_for_job", limit))
        return self.articles


def _job_detail(status: JobStatus = JobStatus.ACTIVE, version: int = 3):
    return CollectionJobDetail(
        id=11,
        job_name="晨间群采集",
        pipeline_type=PipelineType.GROUP,
        target_names=("核心群A",),
        schedule=ScheduleSpec(
            effective_start_at=NOW,
            effective_end_at=datetime(2026, 7, 12, 18, 0, tzinfo=ZONE),
            daily_window_start=time(9, 0),
            daily_window_end=time(18, 0),
            interval_seconds=30,
        ),
        status=status,
        next_run_at=NOW,
        version=version,
    )


class FakeJobService:
    def __init__(self) -> None:
        self.detail = _job_detail()
        self.calls: list[tuple] = []
        self.create_error: Exception | None = None
        self.stop_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.list_error: Exception | None = None
        self.total_count = 1
        self.summaries = [
            CollectionJobSummary(
                id=11,
                job_name="晨间群采集",
                pipeline_type=PipelineType.GROUP,
                status=JobStatus.ACTIVE,
                next_run_at=NOW,
                target_count=1,
                version=3,
            )
        ]

    def create_job(self, command, actor, now):
        self.calls.append(("create_job", command, actor, now))
        if self.create_error is not None:
            raise self.create_error
        if (
            command.pipeline_type is PipelineType.ARTICLE
            and command.interval_seconds < 600
        ):
            raise JobValidationError("interval_seconds must be at least 600")
        return 41

    def get_job(self, job_id):
        self.calls.append(("get_job", job_id))
        if job_id == 404:
            raise JobNotFoundError()
        return self.detail

    def request_stop(self, job_id, expected_version, actor, now):
        self.calls.append(
            ("request_stop", job_id, expected_version, actor, now)
        )
        if self.stop_error is not None:
            raise self.stop_error
        self.detail = replace(
            self.detail,
            status=JobStatus.STOP_REQUESTED,
            version=self.detail.version + 1,
        )
        return JobStatus.STOP_REQUESTED

    def delete_job(self, job_id, expected_version, actor, now):
        self.calls.append(
            ("delete_job", job_id, expected_version, actor, now)
        )
        if self.delete_error is not None:
            raise self.delete_error
        return True

    def list_jobs(self, filters, page, page_size):
        self.calls.append(("list_jobs", filters, page, page_size))
        if self.list_error is not None:
            raise self.list_error
        return PagedResult(self.summaries, page, page_size, self.total_count)


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def auth_service() -> FakeAuthService:
    return FakeAuthService()


@pytest.fixture
def source_service() -> FakeSourceService:
    return FakeSourceService()


@pytest.fixture
def job_service() -> FakeJobService:
    return FakeJobService()


@pytest.fixture
def app(config, auth_service, source_service, job_service) -> FastAPI:
    application = create_app(
        config,
        auth_service=auth_service,
        source_service=source_service,
    )
    application.state.job_service = job_service
    return application


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authenticated_client(raw_client: TestClient) -> TestClient:
    raw_client.cookies.set("weinsight_session", "session-token")
    raw_client.cookies.set("weinsight_csrf", "csrf-token")
    return raw_client


def _valid_article_form(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "csrf_token": "csrf-token",
        "job_name": "晚间公众号采集",
        "pipeline_type": "article",
        "target_ids": "9",
        "effective_start_at": "2026-07-10T09:00",
        "effective_end_at": "2026-07-12T18:00",
        "daily_window_start": "09:00",
        "daily_window_end": "18:00",
        "interval_minutes": "10",
    }
    values.update(changes)
    return values


def test_create_article_job_rejects_nine_minutes(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/jobs",
        data=_valid_article_form(interval_minutes="9"),
    )

    assert response.status_code == 422
    assert "最小间隔为 10 分钟" in response.text


def test_stop_active_job_shows_stopping(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/jobs/11/stop",
        data={"csrf_token": "csrf-token", "version": "3"},
    )

    assert response.status_code == 200
    assert "停止中" in response.text


def test_active_job_has_no_delete_action(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/jobs/11")

    assert response.status_code == 200
    assert "删除任务" not in response.text


def test_jobs_require_authentication(raw_client: TestClient) -> None:
    response = raw_client.get("/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_job_list_parses_filters_paginates_and_escapes_names(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    job_service.summaries = [
        replace(job_service.summaries[0], job_name="<script>alert(1)</script>")
    ]
    job_service.total_count = 3

    response = authenticated_client.get(
        "/jobs?pipeline=group&status=active&name=%E6%99%A8%E9%97%B4&page=2&page_size=1"
    )

    assert response.status_code == 200
    assert job_service.calls[0][0] == "list_jobs"
    filters, page, page_size = job_service.calls[0][1:]
    assert filters.pipeline_type is PipelineType.GROUP
    assert filters.status is JobStatus.ACTIVE
    assert filters.name_contains == "晨间"
    assert (page, page_size) == (2, 1)
    assert "<script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "pipeline=group" in response.text
    assert "status=active" in response.text
    assert "name=%E6%99%A8%E9%97%B4" in response.text
    assert "page_size=1" in response.text


@pytest.mark.parametrize(
    "query",
    [
        "pipeline=group&pipeline=article",
        "status=active&status=stopped",
        "page=1&page=2",
        "page_size=20&page_size=30",
        "unknown=value",
        "pipeline=other",
        "status=running",
        "page=0",
        "page_size=101",
        "name=" + "x" * 201,
    ],
)
def test_job_list_rejects_ambiguous_or_invalid_query_without_service_call(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    query: str,
) -> None:
    response = authenticated_client.get(f"/jobs?{query}")

    assert response.status_code == 422
    assert "请检查筛选条件" in response.text
    assert job_service.calls == []


def test_new_job_loads_only_selected_pipeline_sources(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    article = authenticated_client.get("/jobs/new?pipeline=article")

    assert article.status_code == 200
    assert "行业观察" in article.text
    assert "核心群A" not in article.text
    assert source_service.calls == [("list_enabled_articles_for_job", 100)]

    source_service.calls.clear()
    group = authenticated_client.get("/jobs/new?pipeline=group")

    assert group.status_code == 200
    assert "核心群A" in group.text
    assert "行业观察" not in group.text
    assert source_service.calls == [("list_enabled_groups_for_job", 100)]


@pytest.mark.parametrize(
    "query", ["pipeline=group&pipeline=article", "pipeline=other", "extra=1"]
)
def test_new_job_rejects_invalid_pipeline_query_without_source_query(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
    query: str,
) -> None:
    response = authenticated_client.get(f"/jobs/new?{query}")

    assert response.status_code == 422
    assert source_service.calls == []


def test_new_job_uses_pipeline_specific_interval_units_and_minimums(
    authenticated_client: TestClient,
) -> None:
    article = authenticated_client.get("/jobs/new?pipeline=article")
    group = authenticated_client.get("/jobs/new?pipeline=group")

    assert 'name="interval_minutes"' in article.text
    assert 'min="10"' in article.text
    assert "公众号任务频率按分钟填写" in article.text
    assert 'name="interval_seconds"' not in article.text
    assert 'name="interval_seconds"' in group.text
    assert 'min="30"' in group.text
    assert "微信群任务频率按秒填写" in group.text
    assert 'name="interval_minutes"' not in group.text
    assert 'href="/jobs/new?pipeline=group"' in article.text
    assert 'href="/jobs/new?pipeline=article"' in group.text


def test_create_job_builds_timezone_aware_command_and_redirects_to_detail(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    response = authenticated_client.post(
        "/jobs",
        data={
            **_valid_article_form(),
            "target_ids": ["9", "9"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/jobs/41"
    _, command, actor, now = job_service.calls[0]
    assert command.target_ids == (9,)
    assert command.interval_seconds == 600
    assert command.effective_start_at == datetime(
        2026, 7, 10, 9, 0, tzinfo=ZONE
    )
    assert command.effective_start_at.tzinfo is ZONE
    assert command.daily_window_start == time(9, 0)
    assert actor == "admin"
    assert isinstance(now.tzinfo, ZoneInfo)
    assert now.tzinfo.key == "Asia/Shanghai"


def test_create_group_job_uses_seconds_without_minutes_conversion(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    values = _valid_article_form(
        job_name="群任务",
        pipeline_type="group",
        target_ids="7",
        interval_seconds="30",
    )
    values.pop("interval_minutes")

    response = authenticated_client.post("/jobs", data=values)

    assert response.status_code == 200
    command = job_service.calls[0][1]
    assert command.pipeline_type is PipelineType.GROUP
    assert command.interval_seconds == 30


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_start_at", "2026-07-10T09:00+08:00"),
        ("effective_start_at", "2026-07-10T09:00Z"),
        ("effective_start_at", "2026-07-10 09:00"),
        ("effective_start_at", "2026-07-10T09:00:00"),
        ("daily_window_start", "9:00"),
        ("daily_window_start", "09:00:00"),
        ("daily_window_start", "09:00+08:00"),
        ("target_ids", "on"),
        ("target_ids", "0"),
        ("target_ids", "-1"),
        ("interval_minutes", "10.0"),
        ("interval_minutes", " 10"),
    ],
)
def test_create_job_rejects_spoofed_or_noncanonical_form_values(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    field: str,
    value: str,
) -> None:
    response = authenticated_client.post(
        "/jobs", data=_valid_article_form(**{field: value})
    )

    assert response.status_code == 422
    assert "请检查任务参数" in response.text
    assert job_service.calls == []


def test_create_job_rejects_duplicate_single_value_field(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    response = authenticated_client.post(
        "/jobs",
        content=(
            "csrf_token=csrf-token&job_name=A&job_name=B&pipeline_type=article&"
            "target_ids=9&effective_start_at=2026-07-10T09%3A00&"
            "effective_end_at=2026-07-12T18%3A00&daily_window_start=09%3A00&"
            "daily_window_end=18%3A00&interval_minutes=10"
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    assert "重复字段" in response.text
    assert job_service.calls == []


def test_create_job_rejects_unknown_field_and_duplicate_csrf(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    unknown = authenticated_client.post(
        "/jobs", data=_valid_article_form(debug="1")
    )
    duplicate_csrf = authenticated_client.post(
        "/jobs",
        content=(
            "csrf_token=csrf-token&csrf_token=csrf-token&job_name=A&"
            "pipeline_type=article&target_ids=9&"
            "effective_start_at=2026-07-10T09%3A00&"
            "effective_end_at=2026-07-12T18%3A00&daily_window_start=09%3A00&"
            "daily_window_end=18%3A00&interval_minutes=10"
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert unknown.status_code == 422
    assert duplicate_csrf.status_code == 422
    assert job_service.calls == []


def test_create_overlap_shows_escaped_job_names_without_internal_detail(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    job_service.create_error = JobOverlapError(
        ["已有晨间任务", "<script>bad</script>"]
    )

    response = authenticated_client.post("/jobs", data=_valid_article_form())

    assert response.status_code == 409
    assert "已有晨间任务" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in response.text
    assert "targets overlap existing collection jobs" not in response.text


@pytest.mark.parametrize(
    ("error", "safe_text"),
    [
        (JobTargetNotFoundError("private table"), "名单已不存在"),
        (JobTargetDisabledError("private enabled state"), "名单已停用"),
        (JobMixedPipelineError("private target type"), "同一采集链路"),
    ],
)
def test_create_target_races_are_safely_mapped(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    error: Exception,
    safe_text: str,
) -> None:
    job_service.create_error = error

    response = authenticated_client.post("/jobs", data=_valid_article_form())

    assert response.status_code in {409, 422}
    assert safe_text in response.text
    assert str(error) not in response.text


@pytest.mark.parametrize(
    ("status", "expected_action", "missing_action", "text"),
    [
        (JobStatus.SCHEDULED, "/jobs/11/stop", "/jobs/11/delete", "停止任务"),
        (JobStatus.ACTIVE, "/jobs/11/stop", "/jobs/11/delete", "停止任务"),
        (JobStatus.STOP_REQUESTED, None, "/jobs/11/delete", "停止中"),
        (JobStatus.STOPPED, "/jobs/11/delete", "/jobs/11/stop", "删除任务"),
        (JobStatus.COMPLETED, "/jobs/11/delete", "/jobs/11/stop", "删除任务"),
        (JobStatus.DELETED, None, "/jobs/11/stop", "已删除"),
    ],
)
def test_job_detail_only_renders_legal_state_actions(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    status: JobStatus,
    expected_action: str | None,
    missing_action: str,
    text: str,
) -> None:
    job_service.detail = replace(job_service.detail, status=status)

    response = authenticated_client.get("/jobs/11")

    assert response.status_code == 200
    assert text in response.text
    if expected_action is not None:
        assert f'action="{expected_action}"' in response.text
    assert f'action="{missing_action}"' not in response.text


def test_stop_version_conflict_refreshes_current_detail(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    job_service.stop_error = JobVersionConflictError("database version=secret")
    job_service.detail = replace(
        job_service.detail,
        job_name="已刷新任务",
        status=JobStatus.STOP_REQUESTED,
        version=4,
    )

    response = authenticated_client.post(
        "/jobs/11/stop",
        data={"csrf_token": "csrf-token", "version": "3"},
    )

    assert response.status_code == 409
    assert "任务状态已更新" in response.text
    assert "已刷新任务" in response.text
    assert "停止中" in response.text
    assert "database version=secret" not in response.text
    assert [call[0] for call in job_service.calls] == [
        "request_stop",
        "get_job",
    ]


def test_delete_version_conflict_refreshes_current_detail(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    job_service.detail = replace(job_service.detail, status=JobStatus.STOPPED)
    job_service.delete_error = JobVersionConflictError("database detail")

    response = authenticated_client.post(
        "/jobs/11/delete",
        data={"csrf_token": "csrf-token", "version": "3"},
    )

    assert response.status_code == 409
    assert "任务状态已更新" in response.text
    assert "删除任务" in response.text
    assert "database detail" not in response.text
    assert [call[0] for call in job_service.calls] == [
        "delete_job",
        "get_job",
    ]


def test_delete_stopped_job_redirects_to_list(
    authenticated_client: TestClient,
    job_service: FakeJobService,
) -> None:
    job_service.detail = replace(job_service.detail, status=JobStatus.STOPPED)

    response = authenticated_client.post(
        "/jobs/11/delete",
        data={"csrf_token": "csrf-token", "version": "3"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/jobs"


@pytest.mark.parametrize("action", ["stop", "delete"])
def test_illegal_state_action_returns_safe_refreshed_409(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    action: str,
) -> None:
    error = JobStateTransitionError(JobStatus.ACTIVE, action)
    if action == "stop":
        job_service.stop_error = error
    else:
        job_service.delete_error = error

    response = authenticated_client.post(
        f"/jobs/11/{action}",
        data={"csrf_token": "csrf-token", "version": "3"},
    )

    assert response.status_code == 409
    assert "当前状态不允许此操作" in response.text
    assert str(error) not in response.text
    assert job_service.calls[-1] == ("get_job", 11)


@pytest.mark.parametrize(
    "path", ["/jobs/11/stop", "/jobs/11/delete"]
)
def test_job_mutation_rejects_duplicate_version_and_unknown_fields(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    path: str,
) -> None:
    duplicate = authenticated_client.post(
        path,
        content="csrf_token=csrf-token&version=3&version=4",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    unknown = authenticated_client.post(
        path,
        data={"csrf_token": "csrf-token", "version": "3", "force": "1"},
    )

    assert duplicate.status_code == 422
    assert unknown.status_code == 422
    assert job_service.calls == []


@pytest.mark.parametrize("path", ["/jobs/11/stop", "/jobs/11/delete"])
def test_job_mutation_paths_do_not_accept_get(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 405
    assert job_service.calls == []


def test_missing_job_returns_safe_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/jobs/404")

    assert response.status_code == 404
    assert "采集任务不存在" in response.text


class JobFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "form":
            self.current = {
                "method": values.get("method"),
                "action": values.get("action"),
                "inputs": [],
            }
        elif tag == "input" and self.current is not None:
            self.current["inputs"].append(values)  # type: ignore[union-attr]

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


@pytest.mark.parametrize(
    ("path", "expected_actions"),
    [
        ("/jobs/new?pipeline=group", {"/jobs"}),
        ("/jobs/11", {"/jobs/11/stop"}),
    ],
)
def test_each_job_write_form_is_post_with_exactly_one_csrf_and_version(
    authenticated_client: TestClient,
    path: str,
    expected_actions: set[str],
) -> None:
    response = authenticated_client.get(path)
    parser = JobFormParser()
    parser.feed(response.text)
    job_forms = [
        form for form in parser.forms if str(form["action"]).startswith("/jobs")
    ]

    assert {str(form["action"]) for form in job_forms} == expected_actions
    for form in job_forms:
        assert str(form["method"]).lower() == "post"
        csrf = [
            item
            for item in form["inputs"]
            if item.get("name") == "csrf_token"
        ]
        assert csrf == [
            {"type": "hidden", "name": "csrf_token", "value": "csrf-token"}
        ]
        if form["action"] != "/jobs":
            versions = [
                item for item in form["inputs"] if item.get("name") == "version"
            ]
            assert versions == [
                {"type": "hidden", "name": "version", "value": "3"}
            ]


def test_detail_explains_cross_midnight_and_history_retention(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/jobs/11")

    assert "开始时间等于结束时间表示全天" in response.text
    assert "开始时间晚于结束时间表示跨午夜" in response.text
    assert "删除仅隐藏任务，运行历史和采集结果会保留" in response.text
    assert "当前仍使用默认密码 admin123456" in response.text


def test_create_app_accepts_injected_job_service(
    config: Config,
    auth_service: FakeAuthService,
    source_service: FakeSourceService,
    job_service: FakeJobService,
) -> None:
    app = create_app(
        config,
        auth_service=auth_service,
        source_service=source_service,
        job_service=job_service,
    )

    assert app.state.job_service is job_service


def test_create_app_default_job_repo_shares_the_single_engine(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    monkeypatch.setitem(
        create_app.__globals__, "create_mysql_engine", lambda mysql: engine
    )

    app = create_app(config)

    assert app.state.job_service.repo.engine is engine


def test_all_job_and_source_calls_run_in_threadpool(
    authenticated_client: TestClient,
    job_service: FakeJobService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.web.routes import jobs as job_routes

    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(job_routes, "run_in_threadpool", recording_threadpool)

    assert authenticated_client.get("/jobs").status_code == 200
    assert authenticated_client.get("/jobs/new?pipeline=group").status_code == 200
    assert authenticated_client.get("/jobs/11").status_code == 200
    assert authenticated_client.post(
        "/jobs", data=_valid_article_form()
    ).status_code == 200
    assert authenticated_client.post(
        "/jobs/11/stop",
        data={"csrf_token": "csrf-token", "version": "3"},
    ).status_code == 200
    job_service.detail = replace(
        job_service.detail, status=JobStatus.STOPPED, version=4
    )
    assert authenticated_client.post(
        "/jobs/11/delete",
        data={"csrf_token": "csrf-token", "version": "4"},
        follow_redirects=False,
    ).status_code == 303

    assert calls == [
        "list_jobs",
        "list_enabled_groups_for_job",
        "get_job",
        "create_job",
        "get_job",
        "request_stop",
        "get_job",
        "delete_job",
    ]
