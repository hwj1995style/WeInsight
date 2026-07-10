from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.source_management_service import (
    ArticleSourceCommand,
    GroupSourceCommand,
    SourceInUseError,
    SourceManagementService,
    SourceMustBeDisabledError,
    SourceNotFoundError,
    SourceRenameBlockedError,
)
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.storage.group_repo import GroupConfigRecord
from app.storage.source_reference_repo import MysqlSourceReferenceRepo


GROUP_COMMAND = GroupSourceCommand(
    group_name="核心群A",
    is_core_group=True,
    priority=1,
    poll_interval_seconds=30,
    backtrack_pages=1,
    extra_backtrack_pages=3,
    remark=None,
)
ARTICLE_COMMAND = ArticleSourceCommand(
    account_name="行业观察",
    account_type="subscription",
    priority=2,
    poll_interval_minutes=10,
    daily_window_start="07:30",
    daily_window_end="19:30",
    max_articles_per_round=5,
    collect_today_only=True,
    remark=None,
)


class FakeGroupRepo:
    def __init__(self) -> None:
        self.record = GroupConfigRecord(
            id=7,
            group_name="核心群A",
            priority=1,
            poll_interval_seconds=30,
            enabled=True,
            is_core_group=True,
            backtrack_pages=1,
            extra_backtrack_pages=3,
        )
        self.created: list[dict] = []
        self.updated: list[tuple[int, dict]] = []
        self.enabled_calls: list[tuple[int, bool]] = []
        self.deleted_ids: list[int] = []
        self.delete_rowcount = 1
        self.delete_error: Exception | None = None

    def list_groups(self):
        return [self.record]

    def get_group(self, source_id: int):
        return self.record if source_id == 7 else None

    def create_group_config(self, **values):
        self.created.append(values)
        return 7

    def update_group_config(self, source_id: int, **values):
        self.updated.append((source_id, values))
        return 1

    def set_group_enabled(self, source_id: int, enabled: bool):
        self.enabled_calls.append((source_id, enabled))
        self.record = replace(self.record, enabled=enabled)
        return 1

    def delete_group(self, source_id: int):
        if self.delete_error is not None:
            raise self.delete_error
        if self.delete_rowcount:
            self.deleted_ids.append(source_id)
        return self.delete_rowcount


class FakeArticleRepo:
    def __init__(self) -> None:
        self.record = ArticleAccountConfigRecord(
            id=9,
            account_name="行业观察",
            account_type="subscription",
            priority=2,
            poll_interval_minutes=10,
            daily_window_start="07:30:00",
            daily_window_end="19:30:00",
            max_articles_per_round=5,
            enabled=True,
        )
        self.created: list[dict] = []
        self.updated: list[tuple[int, dict]] = []
        self.enabled_calls: list[tuple[int, bool]] = []
        self.deleted_ids: list[int] = []
        self.delete_rowcount = 1

    def list_accounts(self):
        return [self.record]

    def get_account(self, source_id: int):
        return self.record if source_id == 9 else None

    def create_account_config(self, **values):
        self.created.append(values)
        return 9

    def update_account_config(self, source_id: int, **values):
        self.updated.append((source_id, values))
        return 1

    def set_account_enabled(self, source_id: int, enabled: bool):
        self.enabled_calls.append((source_id, enabled))
        self.record = replace(self.record, enabled=enabled)
        return 1

    def delete_account(self, source_id: int):
        if self.delete_rowcount:
            self.deleted_ids.append(source_id)
        return self.delete_rowcount


class FakeReferences:
    def __init__(self) -> None:
        self.active_job_names: list[str] = []
        self.all_job_names: list[str] = []
        self.has_group_history_result = False
        self.has_article_history_result = False

    def list_referencing_jobs(self, source_type, source_id, active_only):
        return list(self.active_job_names if active_only else self.all_job_names)

    def has_group_history(self, group_name):
        return self.has_group_history_result

    def has_article_history(self, account_name):
        return self.has_article_history_result


@pytest.fixture
def group_repo():
    return FakeGroupRepo()


@pytest.fixture
def article_repo():
    return FakeArticleRepo()


@pytest.fixture
def refs():
    return FakeReferences()


@pytest.fixture
def service(group_repo, article_repo, refs):
    return SourceManagementService(group_repo, article_repo, refs)


def test_list_and_create_sources_are_symmetric(service, group_repo, article_repo) -> None:
    assert service.list_groups() == [group_repo.record]
    assert service.list_articles() == [article_repo.record]

    assert service.create_group(GROUP_COMMAND) == 7
    assert service.create_article(ARTICLE_COMMAND) == 9

    assert group_repo.created[0]["enabled"] is True
    assert article_repo.created[0]["enabled"] is True
    assert article_repo.created[0]["dedup_key"] == "article_hash"


def test_active_reference_blocks_disable(service, refs) -> None:
    refs.active_job_names = ["核心群晨间采集"]
    with pytest.raises(SourceInUseError) as exc:
        service.set_group_enabled(source_id=7, enabled=False)
    assert exc.value.job_names == ("核心群晨间采集",)


def test_enable_does_not_require_reference_check(service, group_repo, refs) -> None:
    refs.active_job_names = ["核心群晨间采集"]
    service.set_group_enabled(source_id=7, enabled=True)
    assert group_repo.enabled_calls == [(7, True)]


def test_any_reference_blocks_delete(service, group_repo, refs) -> None:
    group_repo.record = replace(group_repo.record, enabled=False)
    refs.all_job_names = ["已完成任务"]
    with pytest.raises(SourceInUseError):
        service.delete_group(source_id=7)


def test_unreferenced_disabled_source_can_be_deleted(service, group_repo) -> None:
    group_repo.record = replace(group_repo.record, enabled=False)
    service.delete_group(source_id=7)
    assert group_repo.deleted_ids == [7]


def test_delete_requires_existing_disabled_source(service, group_repo) -> None:
    with pytest.raises(SourceMustBeDisabledError):
        service.delete_group(7)
    with pytest.raises(SourceNotFoundError):
        service.delete_group(99)


def test_foreign_key_delete_race_maps_to_source_in_use(service, group_repo) -> None:
    group_repo.record = replace(group_repo.record, enabled=False)
    group_repo.delete_error = IntegrityError(
        "DELETE", {"source_id": 7}, Exception(1451, "foreign key constraint")
    )

    with pytest.raises(SourceInUseError):
        service.delete_group(7)


def test_delete_zero_rows_after_concurrent_enable_returns_conflict(service, group_repo) -> None:
    group_repo.record = replace(group_repo.record, enabled=False)
    group_repo.delete_rowcount = 0

    def current_record(source_id: int):
        return replace(group_repo.record, enabled=True)

    group_repo.get_group = current_record
    with pytest.raises(SourceMustBeDisabledError):
        service.delete_group(7)


def test_source_with_history_cannot_be_renamed(service, refs) -> None:
    refs.has_group_history_result = True
    with pytest.raises(SourceRenameBlockedError):
        service.update_group(7, replace(GROUP_COMMAND, group_name="新群名"))


def test_source_referenced_by_any_task_cannot_be_renamed(service, refs) -> None:
    refs.all_job_names = ["历史任务"]
    with pytest.raises(SourceRenameBlockedError):
        service.update_group(7, replace(GROUP_COMMAND, group_name="新群名"))


def test_unreferenced_source_without_history_can_be_renamed(service, group_repo) -> None:
    service.update_group(7, replace(GROUP_COMMAND, group_name="新群名"))
    assert group_repo.updated[0][0] == 7
    assert group_repo.updated[0][1]["group_name"] == "新群名"


def test_article_rules_are_symmetric(service, article_repo, refs) -> None:
    refs.active_job_names = ["公众号采集"]
    with pytest.raises(SourceInUseError):
        service.set_article_enabled(9, False)

    refs.active_job_names = []
    refs.has_article_history_result = True
    with pytest.raises(SourceRenameBlockedError):
        service.update_article(9, replace(ARTICLE_COMMAND, account_name="新账号"))

    refs.has_article_history_result = False
    article_repo.record = replace(article_repo.record, enabled=False)
    service.delete_article(9)
    assert article_repo.deleted_ids == [9]


@pytest.mark.parametrize(
    "command",
    [
        replace(GROUP_COMMAND, group_name=" "),
        replace(GROUP_COMMAND, priority=0),
        replace(GROUP_COMMAND, priority=101),
        replace(GROUP_COMMAND, poll_interval_seconds=29),
        replace(GROUP_COMMAND, backtrack_pages=-1),
        replace(GROUP_COMMAND, extra_backtrack_pages=-1),
        replace(GROUP_COMMAND, is_core_group=1),
        replace(GROUP_COMMAND, remark="x" * 501),
    ],
)
def test_group_command_is_strictly_validated(service, command) -> None:
    with pytest.raises(ValueError):
        service.create_group(command)


@pytest.mark.parametrize(
    "command",
    [
        replace(ARTICLE_COMMAND, account_name=""),
        replace(ARTICLE_COMMAND, account_type="service"),
        replace(ARTICLE_COMMAND, priority=True),
        replace(ARTICLE_COMMAND, poll_interval_minutes=9),
        replace(ARTICLE_COMMAND, daily_window_start="24:00"),
        replace(ARTICLE_COMMAND, daily_window_end="noon"),
        replace(ARTICLE_COMMAND, max_articles_per_round=0),
        replace(ARTICLE_COMMAND, max_articles_per_round=21),
        replace(ARTICLE_COMMAND, collect_today_only=1),
    ],
)
def test_article_command_is_strictly_validated(service, command) -> None:
    with pytest.raises(ValueError):
        service.create_article(command)


class QueryResult:
    def __init__(self, rows=None, scalar=None) -> None:
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class QueryConnection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return next(self.results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class QueryEngine:
    def __init__(self, results) -> None:
        self.connection = QueryConnection(results)

    def begin(self):
        return self.connection


def test_reference_repo_uses_fixed_columns_and_active_statuses() -> None:
    engine = QueryEngine([QueryResult(rows=[{"job_name": "任务A"}])])
    repo = MysqlSourceReferenceRepo(engine)

    assert repo.list_referencing_jobs("group", 7, active_only=True) == ["任务A"]
    sql, params = engine.connection.executions[0]
    assert "target.group_config_id = :source_id" in sql
    assert "scheduled" in sql and "active" in sql and "stop_requested" in sql
    assert params == {"source_id": 7}


def test_reference_repo_checks_all_business_history_tables() -> None:
    group_engine = QueryEngine([QueryResult(scalar=1)])
    assert MysqlSourceReferenceRepo(group_engine).has_group_history("核心群A") is True
    group_sql, _ = group_engine.connection.executions[0]
    for table in (
        "wechat_group_msg_raw",
        "wechat_group_msg_clean",
        "wechat_group_msg_analysis",
        "wechat_group_daily_report",
        "wechat_group_collect_cursor",
        "wechat_group_collect_log",
    ):
        assert table in group_sql

    article_engine = QueryEngine([QueryResult(scalar=0)])
    assert MysqlSourceReferenceRepo(article_engine).has_article_history("行业观察") is False
    article_sql, _ = article_engine.connection.executions[0]
    for table in (
        "wechat_article_raw",
        "wechat_article_clean",
        "wechat_article_analysis",
        "wechat_article_egg_price_item",
        "wechat_article_daily_report",
        "wechat_article_collect_log",
        "wechat_article_collect_progress",
    ):
        assert table in article_sql
