from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
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
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.storage.group_repo import GroupConfigRecord
from app.web.app import create_app


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
def app(
    config: Config,
    auth_service: FakeAuthService,
    source_service: FakeSourceService,
) -> FastAPI:
    return create_app(
        config,
        auth_service=auth_service,
        source_service=source_service,
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
    assert "当前仍使用默认密码 admin123456" in response.text


def test_article_list_uses_stable_ids_and_escapes_names(
    authenticated_client: TestClient,
    source_service: FakeSourceService,
) -> None:
    source_service.articles[0] = replace(
        source_service.articles[0], account_name='<script>alert("x")</script>'
    )

    response = authenticated_client.get("/sources/articles")

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'href="/sources/articles/9/edit"' in response.text
    assert 'action="/sources/articles/10/delete"' in response.text


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
        ("/sources/articles/new", "/sources/articles"),
        ("/sources/articles/9/edit", "/sources/articles/9"),
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
        priority="3",
        poll_interval_minutes="15",
        daily_window_start="06:00",
        daily_window_end="20:00",
        max_articles_per_round="8",
        collect_today_only="on",
        remark="价格信息",
    )

    created = authenticated_client.post(
        "/sources/articles", data=values, follow_redirects=False
    )
    updated = authenticated_client.post(
        "/sources/articles/9", data=values, follow_redirects=False
    )

    assert created.status_code == 303
    assert updated.status_code == 303
    assert source_service.calls[0] == (
        "create_article",
        ArticleSourceCommand(
            account_name="蛋价早报",
            account_type="official",
            priority=3,
            poll_interval_minutes=15,
            daily_window_start="06:00",
            daily_window_end="20:00",
            max_articles_per_round=8,
            collect_today_only=True,
            remark="价格信息",
        ),
    )
    assert source_service.calls[1][0:2] == ("update_article", 9)


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
        ("/sources/articles/9/disable", ("set_article_enabled", 9, False)),
        ("/sources/articles/9/enable", ("set_article_enabled", 9, True)),
        ("/sources/articles/10/delete", ("delete_article", 10)),
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
            priority="2",
            poll_interval_minutes="9",
            daily_window_start="07:30",
            daily_window_end="19:30",
            max_articles_per_round="5",
            collect_today_only="on",
            remark="不应创建",
        ),
    )

    assert response.status_code == 422
    assert "公众号采集间隔不能少于 10 分钟" in response.text
    assert 'value="九分钟公众号"' in response.text
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
