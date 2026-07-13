from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.services.auth_service import AuthenticatedAdmin
from app.services.source_management_service import (
    ArticleSourceCommand,
    GroupSourceCommand,
    SourceAlreadyExistsError,
    SourceInUseError,
    SourceManagementService,
    SourceMustBeDisabledError,
    SourceNotFoundError,
)
from app.services.article_source_status_service import ArticleSourceStatusPage, ArticleSourceStatusRow
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.storage.group_repo import GroupConfigRecord
from app.web.app import create_app
from app.web.routes import sources as source_routes


class FakeAuthService:
    def __init__(self) -> None:
        self.admin = AuthenticatedAdmin(
            id=1,
            username="admin",
            using_default_password=True,
        )

    def authenticate(
        self,
        session_token: str,
        csrf_token: str | None,
        now: datetime,
    ) -> AuthenticatedAdmin | None:
        if session_token != "session-token":
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
        return session_token == "session-token" and csrf_token == "csrf-token"


class FakeSourceService:
    def __init__(self) -> None:
        self.groups = [
            GroupConfigRecord(
                id=7,
                group_name="核心群A",
                priority=1,
                poll_interval_seconds=30,
                enabled=True,
                is_core_group=True,
                backtrack_pages=1,
                extra_backtrack_pages=3,
                remark="重点关注",
            ),
            GroupConfigRecord(
                id=8,
                group_name="停用群",
                priority=9,
                poll_interval_seconds=60,
                enabled=False,
                is_core_group=False,
                backtrack_pages=2,
                extra_backtrack_pages=4,
            ),
        ]
        self.articles = [
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
                collect_today_only=True,
                remark="每日采集",
                feed_url="https://example.com/industry.xml",
                last_success_collect_time=datetime(2026, 7, 11, 8, 30),
                last_error_code=None,
            ),
            ArticleAccountConfigRecord(
                id=10,
                account_name="停用公众号",
                account_type="official",
                priority=3,
                poll_interval_minutes=20,
                daily_window_start="08:00:00",
                daily_window_end="18:00:00",
                max_articles_per_round=3,
                enabled=False,
                feed_url="https://example.com/disabled.xml",
                last_error_code="RSS_HTTP_ERROR",
            ),
        ]
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    def _raise_error(self) -> None:
        if self.error is not None:
            raise self.error

    def list_groups(self):
        return self.groups

    def list_articles(self):
        return self.articles

    def list_groups_page(self, page: int, page_size: int):
        self._raise_error()
        self.calls.append(("list_groups_page", page, page_size))
        offset = (page - 1) * page_size
        items = self.groups[offset : offset + page_size]
        return SimpleNamespace(
            items=tuple(items),
            page=page,
            page_size=page_size,
            has_previous=page > 1,
            has_next=offset + page_size < len(self.groups),
        )

    def list_articles_page(self, page: int, page_size: int):
        self._raise_error()
        self.calls.append(("list_articles_page", page, page_size))
        offset = (page - 1) * page_size
        items = self.articles[offset : offset + page_size]
        return SimpleNamespace(
            items=tuple(items),
            page=page,
            page_size=page_size,
            has_previous=page > 1,
            has_next=offset + page_size < len(self.articles),
        )

    def get_group(self, source_id: int):
        self._raise_error()
        self.calls.append(("get_group", source_id))
        for source in self.groups:
            if source.id == source_id:
                return source
        raise SourceNotFoundError()

    def get_article(self, source_id: int):
        self._raise_error()
        self.calls.append(("get_article", source_id))
        for source in self.articles:
            if source.id == source_id:
                return source
        raise SourceNotFoundError()

    def create_group(self, command: GroupSourceCommand) -> int:
        self._raise_error()
        self.calls.append(("create_group", command))
        return 11

    def create_article(self, command: ArticleSourceCommand) -> int:
        self._raise_error()
        self.calls.append(("create_article", command))
        return 12

    def update_group(self, source_id: int, command: GroupSourceCommand) -> None:
        self._raise_error()
        self.calls.append(("update_group", source_id, command))

    def update_article(self, source_id: int, command: ArticleSourceCommand) -> None:
        self._raise_error()
        self.calls.append(("update_article", source_id, command))

    def set_group_enabled(self, source_id: int, enabled: bool) -> None:
        self._raise_error()
        self.calls.append(("set_group_enabled", source_id, enabled))

    def set_article_enabled(self, source_id: int, enabled: bool) -> None:
        self._raise_error()
        self.calls.append(("set_article_enabled", source_id, enabled))

    def delete_group(self, source_id: int) -> None:
        self._raise_error()
        self.calls.append(("delete_group", source_id))

    def delete_article(self, source_id: int) -> None:
        self._raise_error()
        self.calls.append(("delete_article", source_id))


class FakeArticleStatusService:
    sync_interval_minutes = 10

    def __init__(self) -> None:
        self.calls = []
        self.error = None

    def list_page(self, page, page_size, now):
        if self.error is not None:
            raise self.error
        self.calls.append((page, page_size, now))
        row = ArticleSourceStatusRow(
            account_name="行业观察<script>", werss_source_id="MP1", upstream_status="active",
            display_status="normal", last_article_time=datetime(2026, 7, 11, 8, 0),
            last_success_collect_time=datetime(2026, 7, 11, 8, 30), article_count=2,
            pending_parse_count=1, pending_analyze_count=0, failed_count=0,
            last_error=None, status_updated_at=datetime(2026, 7, 11, 8, 30),
        )
        return ArticleSourceStatusPage((row,), page, page_size, page > 1, False)


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
def article_status_service() -> FakeArticleStatusService:
    return FakeArticleStatusService()


@pytest.fixture
def app(
    config: Config,
    auth_service: FakeAuthService,
    source_service: FakeSourceService,
    article_status_service: FakeArticleStatusService,
) -> FastAPI:
    return create_app(
        config,
        auth_service=auth_service,
        source_service=source_service,
        article_status_service=article_status_service,
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


def _csrf_data(**values: object) -> dict[str, object]:
    return {"csrf_token": "csrf-token", **values}


def test_group_list_requires_authentication(raw_client: TestClient) -> None:
    response = raw_client.get("/sources/groups", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("path", ["/sources/articles/new", "/sources/articles/7/edit"])
def test_old_article_forms_are_not_available(authenticated_client, path):
    assert authenticated_client.get(path, follow_redirects=False).status_code in {303, 404}


def test_article_page_is_read_only_and_refreshes_with_get(authenticated_client):
    response = authenticated_client.get("/sources/articles")
    assert response.status_code == 200
    assert "公众号状态" in response.text
    assert "每 10 分钟" in response.text
    assert 'href="/sources/articles"' in response.text
    assert "行业观察&lt;script&gt;" in response.text
    for text in ("新增公众号", "编辑公众号", 'action="/sources/articles', ">删除<"):
        assert text not in response.text


@pytest.mark.parametrize("path", [
    "/sources/articles", "/sources/articles/9", "/sources/articles/9/enable",
    "/sources/articles/9/disable", "/sources/articles/9/delete",
])
def test_article_write_routes_are_removed(authenticated_client, path):
    response = authenticated_client.post(path, data={"csrf_token": "csrf-token"}, follow_redirects=False)
    assert response.status_code in {404, 405}


def test_group_list_has_independent_navigation_and_safe_actions(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/groups")

    assert response.status_code == 200
    assert "核心群A" in response.text
    assert 'href="/sources/groups"' in response.text
    assert 'href="/sources/articles"' in response.text
    assert 'action="/sources/groups/7/disable"' in response.text
    assert 'action="/sources/groups/7/delete"' not in response.text
    assert 'action="/sources/groups/8/enable"' in response.text
    assert 'action="/sources/groups/8/delete"' in response.text
    assert "只删除配置，不删除历史采集结果" in response.text
    assert 'name="csrf_token" value="csrf-token"' in response.text
    assert "当前仍使用默认密码" not in response.text
    assert "admin123456" not in response.text


def test_article_list_uses_stable_ids_and_escapes_names(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/articles")
    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'action="/sources/articles' not in response.text


def test_removed_article_new_path_is_unavailable(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/articles/new", follow_redirects=False)
    assert response.status_code in {303, 404}


def test_article_list_shows_feed_health_without_network_call(
    authenticated_client: TestClient,
    article_status_service: FakeArticleStatusService,
) -> None:
    html = authenticated_client.get("/sources/articles").text
    assert "最近成功采集" in html
    assert "最近错误" in html
    assert article_status_service.calls and article_status_service.calls[0][:2] == (1, 20)


def test_create_group_uses_complete_command_and_redirects(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    response = authenticated_client.post(
        "/sources/groups",
        data=_csrf_data(
            group_name="新增群",
            is_core_group="on",
            priority="4",
            poll_interval_seconds="45",
            backtrack_pages="2",
            extra_backtrack_pages="6",
            remark="备注",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/sources/groups"
    assert source_service.calls == [
        (
            "create_group",
            GroupSourceCommand(
                group_name="新增群",
                is_core_group=True,
                priority=4,
                poll_interval_seconds=45,
                backtrack_pages=2,
                extra_backtrack_pages=6,
                remark="备注",
            ),
        )
    ]


def test_group_edit_form_posts_to_stable_id_and_preserves_values(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/groups/7/edit")

    assert response.status_code == 200
    assert 'action="/sources/groups/7"' in response.text
    assert 'value="核心群A"' in response.text
    assert 'name="is_core_group"' in response.text
    assert 'name="csrf_token" value="csrf-token"' in response.text


@pytest.mark.parametrize(
    ("path", "expected_action"),
    [
        ("/sources/groups/new", "/sources/groups"),
    ],
)
def test_source_forms_have_explicit_post_actions_and_csrf(
    authenticated_client: TestClient,
    path: str,
    expected_action: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert f'method="post" action="{expected_action}"' in response.text
    assert 'name="csrf_token" value="csrf-token"' in response.text


def test_update_group_posts_complete_command_to_stable_id(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    response = authenticated_client.post(
        "/sources/groups/7",
        data=_csrf_data(
            group_name="更新群",
            priority="5",
            poll_interval_seconds="90",
            backtrack_pages="4",
            extra_backtrack_pages="8",
            remark="更新备注",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert source_service.calls[0][0:2] == ("update_group", 7)
    assert source_service.calls[0][2].group_name == "更新群"
    assert source_service.calls[0][2].is_core_group is False


def test_create_and_update_article_use_complete_commands(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    values = _csrf_data(
        account_name="蛋价早报",
        account_type="official",
        feed_url="https://example.com/egg.xml",
        request_timeout_seconds="30",
        priority="3",
        poll_interval_minutes="15",
        daily_window_start="06:00",
        daily_window_end="20:00",
        collect_today_only="on",
        remark="价格信息",
    )

    created = authenticated_client.post(
        "/sources/articles", data=values, follow_redirects=False
    )
    updated = authenticated_client.post(
        "/sources/articles/9", data=values, follow_redirects=False
    )

    assert created.status_code in {404, 405}
    assert updated.status_code in {404, 405}
    assert source_service.calls == []


def test_mutation_routes_do_not_accept_get(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/groups/7/disable")

    assert response.status_code == 405


@pytest.mark.parametrize(
    ("path", "expected_call"),
    [
        ("/sources/groups/7/disable", ("set_group_enabled", 7, False)),
        ("/sources/groups/7/enable", ("set_group_enabled", 7, True)),
        ("/sources/groups/8/delete", ("delete_group", 8)),
    ],
)
def test_source_actions_use_post_and_redirect(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
    path: str,
    expected_call: tuple,
) -> None:
    response = authenticated_client.post(
        path,
        data=_csrf_data(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert source_service.calls == [expected_call]


def test_article_nine_minute_interval_is_rejected_and_echoed(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    source_service.error = ValueError("poll_interval_minutes must be at least 10")
    response = authenticated_client.post(
        "/sources/articles",
        data=_csrf_data(
            account_name="九分钟公众号",
            account_type="subscription",
            feed_url="https://example.com/nine.xml",
            request_timeout_seconds="30",
            priority="2",
            poll_interval_minutes="9",
            daily_window_start="07:30",
            daily_window_end="19:30",
            max_articles_per_round="5",
            collect_today_only="on",
            remark="不应创建",
        ),
    )

    assert response.status_code in {404, 405}
    assert source_service.calls == []


def test_delete_in_use_source_returns_safe_409_with_escaped_job_name(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    source_service.error = SourceInUseError(["核心群晨间采集", "<script>bad</script>"])

    response = authenticated_client.post(
        "/sources/groups/7/delete",
        data=_csrf_data(),
    )

    assert response.status_code == 409
    assert "核心群晨间采集" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in response.text
    assert "source is referenced" not in response.text


@pytest.mark.parametrize(
    ("error", "status", "safe_text"),
    [
        (SourceNotFoundError("private table detail"), 404, "采集名单不存在"),
        (ValueError("internal field name"), 422, "请检查表单字段"),
        (SourceMustBeDisabledError("private state"), 409, "请先停用"),
    ],
)
def test_source_errors_are_safely_mapped(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
    error: Exception,
    status: int,
    safe_text: str,
) -> None:
    source_service.error = error

    response = authenticated_client.post(
        "/sources/groups/7/disable",
        data=_csrf_data(),
    )

    assert response.status_code == status
    assert safe_text in response.text
    assert str(error) not in response.text


def test_duplicate_source_name_returns_safe_409_without_database_detail(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    source_service.error = SourceAlreadyExistsError()

    response = authenticated_client.post(
        "/sources/groups",
        data=_csrf_data(
            group_name="重复群",
            priority="1",
            poll_interval_seconds="30",
            backtrack_pages="1",
            extra_backtrack_pages="3",
            remark="",
        ),
    )

    assert response.status_code == 409
    assert "已存在同名采集名单" in response.text
    assert "1062" not in response.text
    assert "Duplicate entry" not in response.text


def test_missing_edit_source_returns_404(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/groups/999/edit")

    assert response.status_code == 404
    assert "采集名单不存在" in response.text


def test_csrf_is_required_for_source_mutations(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    response = authenticated_client.post("/sources/groups/7/disable")

    assert response.status_code == 403
    assert source_service.calls == []


def test_create_app_keeps_injected_source_service(
    config: Config,
    auth_service: FakeAuthService,
    source_service: FakeSourceService,
) -> None:
    app = create_app(
        config,
        auth_service=auth_service,
        source_service=source_service,
    )

    assert app.state.source_service is source_service


def test_create_app_default_source_repositories_share_one_engine(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    monkeypatch.setitem(
        create_app.__globals__, "create_mysql_engine", lambda mysql: engine
    )

    app = create_app(config)

    service = app.state.source_service
    assert isinstance(service, SourceManagementService)
    assert service.group_repo.engine is engine
    assert service.article_repo.engine is engine
    assert service.reference_repo.engine is engine
    assert service.mutation_repo.engine is engine


class SourceFormParser(HTMLParser):
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
        (
            "/sources/groups",
            {
                "/sources/groups/7/disable",
                "/sources/groups/8/enable",
                "/sources/groups/8/delete",
            },
        ),
        (
            "/sources/articles",
            set(),
        ),
        ("/sources/groups/new", {"/sources/groups"}),
        ("/sources/groups/7/edit", {"/sources/groups/7"}),
    ],
)
def test_each_source_write_form_is_post_with_exactly_one_csrf(
    authenticated_client: TestClient,
    path: str,
    expected_actions: set[str],
) -> None:
    response = authenticated_client.get(path)
    parser = SourceFormParser()
    parser.feed(response.text)
    source_forms = [
        form
        for form in parser.forms
        if str(form["action"]).startswith("/sources/")
    ]

    assert response.status_code == 200
    assert {str(form["action"]) for form in source_forms} == expected_actions
    for form in source_forms:
        assert str(form["method"]).lower() == "post"
        csrf_inputs = [
            field
            for field in form["inputs"]
            if field.get("name") == "csrf_token"
        ]
        assert csrf_inputs == [
            {
                "type": "hidden",
                "name": "csrf_token",
                "value": "csrf-token",
            }
        ]


def test_group_list_paginates_and_preserves_page_size(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/sources/groups?page=2&page_size=1")

    assert response.status_code == 200
    assert "停用群" in response.text
    assert "核心群A" not in response.text
    assert 'href="/sources/groups?page=1&amp;page_size=1"' in response.text


def test_invalid_page_boundaries_return_safe_422(
    authenticated_client: TestClient,
    article_status_service: FakeArticleStatusService,
) -> None:
    article_status_service.error = ValueError("page_size must be between 1 and 100")
    response = authenticated_client.get("/sources/articles?page=1&page_size=101")

    assert response.status_code == 422
    assert "请检查表单字段" in response.text


def test_all_source_service_calls_run_in_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(source_routes, "run_in_threadpool", recording_threadpool)
    response = authenticated_client.get("/sources/articles")
    assert response.status_code == 200
    assert calls == ["list_page"]


@pytest.mark.parametrize(
    "path",
    [
        "/sources/groups/7/enable",
        "/sources/groups/7/disable",
        "/sources/groups/7/delete",
        "/sources/articles/9/enable",
        "/sources/articles/9/disable",
        "/sources/articles/9/delete",
    ],
)
def test_all_mutation_paths_reject_get_without_calling_service(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code in {404, 405}
    assert source_service.calls == []


def test_duplicate_business_field_is_rejected_without_service_call(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    response = authenticated_client.post(
        "/sources/groups",
        content=(
            "group_name=A&group_name=B&priority=1&poll_interval_seconds=30&"
            "backtrack_pages=1&extra_backtrack_pages=3"
        ),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": "csrf-token",
        },
    )

    assert response.status_code == 422
    assert "重复字段" in response.text
    assert source_service.calls == []


@pytest.mark.parametrize("checkbox_value", ["yes", "off", "TRUE", "2"])
def test_illegal_checkbox_value_is_rejected_without_service_call(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
    checkbox_value: str,
) -> None:
    response = authenticated_client.post(
        "/sources/groups",
        data=_csrf_data(
            group_name="非法复选框群",
            is_core_group=checkbox_value,
            priority="1",
            poll_interval_seconds="30",
            backtrack_pages="1",
            extra_backtrack_pages="3",
            remark="",
        ),
    )

    assert response.status_code == 422
    assert source_service.calls == []
