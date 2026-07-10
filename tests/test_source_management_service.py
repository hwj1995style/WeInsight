from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.source_management_service import (
    ArticleSourceCommand,
    GroupSourceCommand,
    SourceAlreadyExistsError,
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
        self.create_error: Exception | None = None
        self.page_records = [self.record]
        self.page_calls: list[tuple[int, int]] = []
        self.enabled_job_calls: list[int] = []

    def list_groups(self):
        return [self.record]

    def list_groups_page(self, *, limit: int, offset: int):
        self.page_calls.append((limit, offset))
        return self.page_records

    def list_enabled_groups_for_job(self, *, limit: int):
        self.enabled_job_calls.append(limit)
        return [self.record]

    def get_group(self, source_id: int):
        return self.record if source_id == 7 else None

    def create_group_config(self, **values):
        if self.create_error is not None:
            raise self.create_error
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
        self.page_records = [self.record]
        self.page_calls: list[tuple[int, int]] = []
        self.enabled_job_calls: list[int] = []

    def list_accounts(self):
        return [self.record]

    def list_accounts_page(self, *, limit: int, offset: int):
        self.page_calls.append((limit, offset))
        return self.page_records

    def list_enabled_articles_for_job(self, *, limit: int):
        self.enabled_job_calls.append(limit)
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


def test_group_page_uses_page_size_plus_one_and_reports_navigation(
    service, group_repo
) -> None:
    group_repo.page_records = [
        replace(group_repo.record, id=7),
        replace(group_repo.record, id=8),
        replace(group_repo.record, id=9),
    ]

    page = service.list_groups_page(page=2, page_size=2)

    assert [item.id for item in page.items] == [7, 8]
    assert page.page == 2
    assert page.page_size == 2
    assert page.has_previous is True
    assert page.has_next is True
    assert group_repo.page_calls == [(3, 2)]


def test_article_page_and_public_get_by_id_are_symmetric(
    service, article_repo
) -> None:
    article_repo.page_records = [article_repo.record]

    page = service.list_articles_page(page=1, page_size=20)

    assert page.items == (article_repo.record,)
    assert page.has_previous is False
    assert page.has_next is False
    assert article_repo.page_calls == [(21, 0)]
    assert service.get_group(7).id == 7
    assert service.get_article(9).id == 9
    with pytest.raises(SourceNotFoundError):
        service.get_group(999)
    with pytest.raises(SourceNotFoundError):
        service.get_article(999)


def test_job_source_choices_use_dedicated_bounded_enabled_queries(
    service, group_repo, article_repo
) -> None:
    groups = service.list_enabled_groups_for_job(limit=100)
    articles = service.list_enabled_articles_for_job(limit=17)

    assert groups == (group_repo.record,)
    assert articles == (article_repo.record,)
    assert group_repo.enabled_job_calls == [100]
    assert article_repo.enabled_job_calls == [17]


@pytest.mark.parametrize("limit", [0, 101, True, "10", None])
def test_job_source_choices_reject_invalid_limits_without_querying(
    service, group_repo, article_repo, limit
) -> None:
    with pytest.raises(ValueError, match="limit"):
        service.list_enabled_groups_for_job(limit=limit)
    with pytest.raises(ValueError, match="limit"):
        service.list_enabled_articles_for_job(limit=limit)

    assert group_repo.enabled_job_calls == []
    assert article_repo.enabled_job_calls == []


@pytest.mark.parametrize(
    ("page", "page_size"),
    [(0, 20), (1, 0), (1, 101), (True, 20), (1, True)],
)
def test_source_page_rejects_invalid_boundaries_without_querying(
    service, group_repo, page, page_size
) -> None:
    with pytest.raises(ValueError):
        service.list_groups_page(page=page, page_size=page_size)
    assert group_repo.page_calls == []


def test_mysql_duplicate_name_is_mapped_to_safe_source_conflict(
    service, group_repo
) -> None:
    group_repo.create_error = IntegrityError(
        "INSERT", {}, Exception(1062, "Duplicate entry 'secret' for key")
    )

    with pytest.raises(SourceAlreadyExistsError):
        service.create_group(GROUP_COMMAND)


def test_non_duplicate_integrity_error_from_create_is_not_mapped(
    service, group_repo
) -> None:
    error = IntegrityError("INSERT", {}, Exception(1048, "Column cannot be null"))
    group_repo.create_error = error

    with pytest.raises(IntegrityError) as exc:
        service.create_group(GROUP_COMMAND)
    assert exc.value is error


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
        replace(ARTICLE_COMMAND, daily_window_start="7:30"),
        replace(ARTICLE_COMMAND, daily_window_start="07:30:00.123"),
        replace(ARTICLE_COMMAND, daily_window_start="07:30+08:00"),
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


def test_reference_repo_supports_article_and_all_statuses() -> None:
    engine = QueryEngine([QueryResult(rows=[{"job_name": "历史任务"}])])
    repo = MysqlSourceReferenceRepo(engine)

    assert repo.list_referencing_jobs("article", 9, active_only=False) == ["历史任务"]
    sql, params = engine.connection.executions[0]
    assert "target.article_config_id = :source_id" in sql
    assert "job.status IN" not in sql
    assert params == {"source_id": 9}


def test_reference_repo_rejects_invalid_source_type() -> None:
    repo = MysqlSourceReferenceRepo(QueryEngine([]))
    with pytest.raises(ValueError):
        repo.list_referencing_jobs("invalid", 1, active_only=False)


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
        "wechat_article_route_cache",
        "wechat_article_raw",
        "wechat_article_clean",
        "wechat_article_analysis",
        "wechat_article_egg_price_item",
        "wechat_article_daily_report",
        "wechat_article_collect_log",
        "wechat_article_collect_progress",
    ):
        assert table in article_sql


def test_article_history_route_cache_deletion_mutation_guard() -> None:
    engine = QueryEngine([QueryResult(scalar=0)])

    MysqlSourceReferenceRepo(engine).has_article_history("行业观察")

    sql, _ = engine.connection.executions[0]
    assert "EXISTS(" in sql
    assert "FROM wechat_article_route_cache" in sql


def test_non_foreign_key_integrity_error_is_not_mapped(service, group_repo) -> None:
    group_repo.record = replace(group_repo.record, enabled=False)
    error = IntegrityError("DELETE", {}, Exception(1062, "duplicate entry"))
    group_repo.delete_error = error

    with pytest.raises(IntegrityError) as exc:
        service.delete_group(7)
    assert exc.value is error


def test_non_foreign_key_integrity_error_from_transaction_repo_is_not_mapped(
    group_repo, article_repo, refs
) -> None:
    error = IntegrityError("DELETE", {}, Exception(1062, "duplicate entry"))

    class FailingMutationRepo:
        def delete_group(self, source_id: int) -> None:
            raise error

    service = SourceManagementService(
        group_repo,
        article_repo,
        refs,
        mutation_repo=FailingMutationRepo(),
    )

    with pytest.raises(IntegrityError) as exc:
        service.delete_group(7)
    assert exc.value is error


def test_same_state_enable_is_idempotent(service, group_repo, article_repo) -> None:
    def no_group_change(source_id: int, enabled: bool):
        group_repo.enabled_calls.append((source_id, enabled))
        return 0

    def no_article_change(source_id: int, enabled: bool):
        article_repo.enabled_calls.append((source_id, enabled))
        return 0

    group_repo.set_group_enabled = no_group_change
    article_repo.set_account_enabled = no_article_change

    service.set_group_enabled(7, True)
    service.set_article_enabled(9, True)

    assert group_repo.enabled_calls == [(7, True)]
    assert article_repo.enabled_calls == [(9, True)]
