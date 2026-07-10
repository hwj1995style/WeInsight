from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Generic, Protocol, TypeVar

from sqlalchemy.exc import IntegrityError

from app.storage.article_config_repo import (
    ArticleAccountConfigRecord,
    MysqlArticleAccountConfigRepo,
)
from app.storage.group_repo import GroupConfigRecord, MysqlGroupConfigRepo
from app.storage.source_mutation_repo import (
    MysqlSourceMutationRepo,
    SourceMutationInUseError,
    SourceMutationMustBeDisabledError,
    SourceMutationNotFoundError,
    SourceMutationRenameBlockedError,
)
from app.storage.source_reference_repo import MysqlSourceReferenceRepo


SourceRecord = TypeVar("SourceRecord")


@dataclass(frozen=True)
class SourcePage(Generic[SourceRecord]):
    items: tuple[SourceRecord, ...]
    page: int
    page_size: int
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class GroupSourceCommand:
    group_name: str
    is_core_group: bool
    priority: int
    poll_interval_seconds: int
    backtrack_pages: int
    extra_backtrack_pages: int
    remark: str | None


@dataclass(frozen=True)
class ArticleSourceCommand:
    account_name: str
    account_type: str
    priority: int
    poll_interval_minutes: int
    daily_window_start: str
    daily_window_end: str
    max_articles_per_round: int
    collect_today_only: bool
    remark: str | None


class SourceNotFoundError(LookupError):
    pass


class SourceAlreadyExistsError(RuntimeError):
    pass


class SourceMustBeDisabledError(RuntimeError):
    pass


class SourceInUseError(RuntimeError):
    def __init__(self, job_names: list[str] | tuple[str, ...] = ()) -> None:
        self.job_names = tuple(dict.fromkeys(job_names))
        detail = ", ".join(self.job_names) or "concurrent task reference"
        super().__init__(f"source is referenced by collection jobs: {detail}")


class SourceRenameBlockedError(RuntimeError):
    def __init__(self, job_names: list[str] | tuple[str, ...] = ()) -> None:
        self.job_names = tuple(dict.fromkeys(job_names))
        super().__init__(
            "source with collection history or task references cannot be renamed"
        )


class GroupConfigRepo(Protocol):
    def list_groups(self) -> list[GroupConfigRecord]: ...

    def list_groups_page(
        self, *, limit: int, offset: int
    ) -> list[GroupConfigRecord]: ...

    def get_group(self, source_id: int) -> GroupConfigRecord | None: ...

    def create_group_config(self, **values) -> int: ...

    def update_group_config(self, source_id: int, **values) -> int: ...

    def set_group_enabled(self, source_id: int, enabled: bool) -> int: ...

    def delete_group(self, source_id: int) -> int: ...


class ArticleConfigRepo(Protocol):
    def list_accounts(self) -> list[ArticleAccountConfigRecord]: ...

    def list_accounts_page(
        self, *, limit: int, offset: int
    ) -> list[ArticleAccountConfigRecord]: ...

    def get_account(self, source_id: int) -> ArticleAccountConfigRecord | None: ...

    def create_account_config(self, **values) -> int: ...

    def update_account_config(self, source_id: int, **values) -> int: ...

    def set_account_enabled(self, source_id: int, enabled: bool) -> int: ...

    def delete_account(self, source_id: int) -> int: ...


class SourceReferenceRepo(Protocol):
    def list_referencing_jobs(
        self, source_type: str, source_id: int, active_only: bool
    ) -> list[str]: ...

    def has_group_history(self, group_name: str) -> bool: ...

    def has_article_history(self, account_name: str) -> bool: ...


class SourceMutationRepo(Protocol):
    def update_group(self, source_id: int, **values) -> None: ...

    def update_article(self, source_id: int, **values) -> None: ...

    def set_group_enabled(self, source_id: int, enabled: bool) -> None: ...

    def set_article_enabled(self, source_id: int, enabled: bool) -> None: ...

    def delete_group(self, source_id: int) -> None: ...

    def delete_article(self, source_id: int) -> None: ...


class SourceManagementService:
    def __init__(
        self,
        group_repo: GroupConfigRepo,
        article_repo: ArticleConfigRepo,
        reference_repo: SourceReferenceRepo,
        mutation_repo: SourceMutationRepo | None = None,
    ) -> None:
        self.group_repo = group_repo
        self.article_repo = article_repo
        self.reference_repo = reference_repo
        self.mutation_repo = mutation_repo
        if self.mutation_repo is None:
            self.mutation_repo = self._mysql_mutation_repo(
                group_repo, article_repo, reference_repo
            )

    def list_groups(self) -> list[GroupConfigRecord]:
        return self.group_repo.list_groups()

    def list_articles(self) -> list[ArticleAccountConfigRecord]:
        return self.article_repo.list_accounts()

    def list_groups_page(
        self, page: int, page_size: int
    ) -> SourcePage[GroupConfigRecord]:
        self._validate_page(page, page_size)
        rows = self.group_repo.list_groups_page(
            limit=page_size + 1,
            offset=(page - 1) * page_size,
        )
        return SourcePage(
            items=tuple(rows[:page_size]),
            page=page,
            page_size=page_size,
            has_previous=page > 1,
            has_next=len(rows) > page_size,
        )

    def list_articles_page(
        self, page: int, page_size: int
    ) -> SourcePage[ArticleAccountConfigRecord]:
        self._validate_page(page, page_size)
        rows = self.article_repo.list_accounts_page(
            limit=page_size + 1,
            offset=(page - 1) * page_size,
        )
        return SourcePage(
            items=tuple(rows[:page_size]),
            page=page,
            page_size=page_size,
            has_previous=page > 1,
            has_next=len(rows) > page_size,
        )

    def get_group(self, source_id: int) -> GroupConfigRecord:
        self._validate_source_id(source_id)
        return self._get_group(source_id)

    def get_article(self, source_id: int) -> ArticleAccountConfigRecord:
        self._validate_source_id(source_id)
        return self._get_article(source_id)

    def create_group(self, command: GroupSourceCommand) -> int:
        self._validate_group_command(command)
        try:
            return self.group_repo.create_group_config(
                enabled=True,
                **self._group_values(command),
            )
        except IntegrityError as exc:
            self._raise_if_duplicate(exc)
            raise

    def create_article(self, command: ArticleSourceCommand) -> int:
        self._validate_article_command(command)
        try:
            return self.article_repo.create_account_config(
                enabled=True,
                dedup_key="article_hash",
                **self._article_values(command),
            )
        except IntegrityError as exc:
            self._raise_if_duplicate(exc)
            raise

    def update_group(self, source_id: int, command: GroupSourceCommand) -> None:
        self._validate_source_id(source_id)
        self._validate_group_command(command)
        if self.mutation_repo is not None:
            self._run_mutation(
                lambda: self.mutation_repo.update_group(
                    source_id, **self._group_values(command)
                ),
                map_duplicate=True,
            )
            return
        # Non-MySQL adapters and test doubles use the protocol path below. Concrete
        # MySQL repositories are always routed through MysqlSourceMutationRepo.
        current = self._get_group(source_id)
        if command.group_name != current.group_name:
            jobs = self.reference_repo.list_referencing_jobs(
                "group", source_id, active_only=False
            )
            if jobs or self.reference_repo.has_group_history(current.group_name):
                raise SourceRenameBlockedError(jobs)
        try:
            affected = self.group_repo.update_group_config(
                source_id, **self._group_values(command)
            )
        except IntegrityError as exc:
            self._raise_if_duplicate(exc)
            raise
        if affected == 0:
            raise SourceNotFoundError(f"group source not found: {source_id}")

    def update_article(self, source_id: int, command: ArticleSourceCommand) -> None:
        self._validate_source_id(source_id)
        self._validate_article_command(command)
        if self.mutation_repo is not None:
            self._run_mutation(
                lambda: self.mutation_repo.update_article(
                    source_id, **self._article_values(command)
                ),
                map_duplicate=True,
            )
            return
        current = self._get_article(source_id)
        if command.account_name != current.account_name:
            jobs = self.reference_repo.list_referencing_jobs(
                "article", source_id, active_only=False
            )
            if jobs or self.reference_repo.has_article_history(current.account_name):
                raise SourceRenameBlockedError(jobs)
        try:
            affected = self.article_repo.update_account_config(
                source_id, **self._article_values(command)
            )
        except IntegrityError as exc:
            self._raise_if_duplicate(exc)
            raise
        if affected == 0:
            raise SourceNotFoundError(f"article source not found: {source_id}")

    def set_group_enabled(self, source_id: int, enabled: bool) -> None:
        self._validate_source_id(source_id)
        self._validate_enabled(enabled)
        if self.mutation_repo is not None:
            self._run_mutation(
                lambda: self.mutation_repo.set_group_enabled(source_id, enabled)
            )
            return
        self._get_group(source_id)
        if not enabled:
            jobs = self.reference_repo.list_referencing_jobs(
                "group", source_id, active_only=True
            )
            if jobs:
                raise SourceInUseError(jobs)
        if self.group_repo.set_group_enabled(source_id, enabled) == 0:
            self._get_group(source_id)

    def set_article_enabled(self, source_id: int, enabled: bool) -> None:
        self._validate_source_id(source_id)
        self._validate_enabled(enabled)
        if self.mutation_repo is not None:
            self._run_mutation(
                lambda: self.mutation_repo.set_article_enabled(source_id, enabled)
            )
            return
        self._get_article(source_id)
        if not enabled:
            jobs = self.reference_repo.list_referencing_jobs(
                "article", source_id, active_only=True
            )
            if jobs:
                raise SourceInUseError(jobs)
        if self.article_repo.set_account_enabled(source_id, enabled) == 0:
            self._get_article(source_id)

    def delete_group(self, source_id: int) -> None:
        self._validate_source_id(source_id)
        if self.mutation_repo is not None:
            self._run_mutation(lambda: self.mutation_repo.delete_group(source_id))
            return
        current = self._get_group(source_id)
        if current.enabled:
            raise SourceMustBeDisabledError("group source must be disabled")
        jobs = self.reference_repo.list_referencing_jobs(
            "group", source_id, active_only=False
        )
        if jobs:
            raise SourceInUseError(jobs)
        try:
            affected = self.group_repo.delete_group(source_id)
        except IntegrityError as exc:
            self._raise_if_foreign_key_conflict(exc)
            raise
        if affected == 0:
            self._raise_delete_conflict("group", source_id)

    def delete_article(self, source_id: int) -> None:
        self._validate_source_id(source_id)
        if self.mutation_repo is not None:
            self._run_mutation(lambda: self.mutation_repo.delete_article(source_id))
            return
        current = self._get_article(source_id)
        if current.enabled:
            raise SourceMustBeDisabledError("article source must be disabled")
        jobs = self.reference_repo.list_referencing_jobs(
            "article", source_id, active_only=False
        )
        if jobs:
            raise SourceInUseError(jobs)
        try:
            affected = self.article_repo.delete_account(source_id)
        except IntegrityError as exc:
            self._raise_if_foreign_key_conflict(exc)
            raise
        if affected == 0:
            self._raise_delete_conflict("article", source_id)

    def _raise_delete_conflict(self, source_type: str, source_id: int) -> None:
        if source_type == "group":
            current = self.group_repo.get_group(source_id)
        else:
            current = self.article_repo.get_account(source_id)
        if current is None:
            raise SourceNotFoundError(f"{source_type} source not found: {source_id}")
        if current.enabled:
            raise SourceMustBeDisabledError(f"{source_type} source must be disabled")
        jobs = self.reference_repo.list_referencing_jobs(
            source_type, source_id, active_only=False
        )
        raise SourceInUseError(jobs)

    def _get_group(self, source_id: int) -> GroupConfigRecord:
        current = self.group_repo.get_group(source_id)
        if current is None:
            raise SourceNotFoundError(f"group source not found: {source_id}")
        return current

    def _get_article(self, source_id: int) -> ArticleAccountConfigRecord:
        current = self.article_repo.get_account(source_id)
        if current is None:
            raise SourceNotFoundError(f"article source not found: {source_id}")
        return current

    @staticmethod
    def _group_values(command: GroupSourceCommand) -> dict:
        return {
            "group_name": command.group_name,
            "is_core_group": command.is_core_group,
            "priority": command.priority,
            "poll_interval_seconds": command.poll_interval_seconds,
            "backtrack_pages": command.backtrack_pages,
            "extra_backtrack_pages": command.extra_backtrack_pages,
            "remark": command.remark,
        }

    @staticmethod
    def _article_values(command: ArticleSourceCommand) -> dict:
        return {
            "account_name": command.account_name,
            "account_type": command.account_type,
            "priority": command.priority,
            "poll_interval_minutes": command.poll_interval_minutes,
            "daily_window_start": command.daily_window_start,
            "daily_window_end": command.daily_window_end,
            "max_articles_per_round": command.max_articles_per_round,
            "collect_today_only": command.collect_today_only,
            "remark": command.remark,
        }

    @classmethod
    def _validate_group_command(cls, command: GroupSourceCommand) -> None:
        cls._validate_name(command.group_name, "group_name")
        cls._validate_bool(command.is_core_group, "is_core_group")
        cls._validate_integer(command.priority, "priority", minimum=1, maximum=100)
        cls._validate_integer(
            command.poll_interval_seconds,
            "poll_interval_seconds",
            minimum=30,
        )
        cls._validate_integer(command.backtrack_pages, "backtrack_pages", minimum=0)
        cls._validate_integer(
            command.extra_backtrack_pages, "extra_backtrack_pages", minimum=0
        )
        cls._validate_remark(command.remark)

    @classmethod
    def _validate_article_command(cls, command: ArticleSourceCommand) -> None:
        cls._validate_name(command.account_name, "account_name")
        if not isinstance(command.account_type, str) or command.account_type not in {
            "official",
            "subscription",
        }:
            raise ValueError("account_type must be official or subscription")
        cls._validate_integer(command.priority, "priority", minimum=1, maximum=100)
        cls._validate_integer(
            command.poll_interval_minutes,
            "poll_interval_minutes",
            minimum=10,
        )
        cls._validate_time(command.daily_window_start, "daily_window_start")
        cls._validate_time(command.daily_window_end, "daily_window_end")
        cls._validate_integer(
            command.max_articles_per_round,
            "max_articles_per_round",
            minimum=1,
            maximum=20,
        )
        cls._validate_bool(command.collect_today_only, "collect_today_only")
        cls._validate_remark(command.remark)

    @staticmethod
    def _validate_name(value: str, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must not be empty")
        if value != value.strip():
            raise ValueError(f"{field} must not have surrounding whitespace")
        if len(value) > 200:
            raise ValueError(f"{field} must be at most 200 characters")

    @staticmethod
    def _validate_integer(
        value: int, field: str, *, minimum: int, maximum: int | None = None
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        if value < minimum or (maximum is not None and value > maximum):
            suffix = f" and {maximum}" if maximum is not None else ""
            raise ValueError(f"{field} must be between {minimum}{suffix}")

    @staticmethod
    def _validate_bool(value: bool, field: str) -> None:
        if type(value) is not bool:
            raise ValueError(f"{field} must be a boolean")

    @staticmethod
    def _validate_remark(value: str | None) -> None:
        if value is not None and (not isinstance(value, str) or len(value) > 500):
            raise ValueError("remark must be at most 500 characters")

    @staticmethod
    def _validate_time(value: str, field: str) -> None:
        if not isinstance(value, str) or re.fullmatch(
            r"[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value
        ) is None:
            raise ValueError(f"{field} must be a valid time")
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid time") from exc
        if parsed.tzinfo is not None:
            raise ValueError(f"{field} must not include a timezone")

    @staticmethod
    def _validate_source_id(source_id: int) -> None:
        if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 1:
            raise ValueError("source_id must be a positive integer")

    @staticmethod
    def _validate_enabled(enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")

    @classmethod
    def _validate_page(cls, page: int, page_size: int) -> None:
        cls._validate_integer(page, "page", minimum=1)
        cls._validate_integer(page_size, "page_size", minimum=1, maximum=100)

    @staticmethod
    def _raise_if_foreign_key_conflict(exc: IntegrityError) -> None:
        args = getattr(exc.orig, "args", ())
        code = args[0] if args else None
        message = str(exc.orig).lower()
        if code in {1451, 1452} or "foreign key" in message:
            raise SourceInUseError() from exc

    @staticmethod
    def _raise_if_duplicate(exc: IntegrityError) -> None:
        args = getattr(exc.orig, "args", ())
        code = args[0] if args else None
        if code == 1062:
            raise SourceAlreadyExistsError() from exc

    @staticmethod
    def _mysql_mutation_repo(
        group_repo: GroupConfigRepo,
        article_repo: ArticleConfigRepo,
        reference_repo: SourceReferenceRepo,
    ) -> SourceMutationRepo | None:
        mysql_repos = (
            isinstance(group_repo, MysqlGroupConfigRepo),
            isinstance(article_repo, MysqlArticleAccountConfigRepo),
            isinstance(reference_repo, MysqlSourceReferenceRepo),
        )
        if not any(mysql_repos):
            return None
        if not all(mysql_repos):
            raise ValueError(
                "real MySQL source management requires all three MySQL repositories"
            )
        engines = (group_repo.engine, article_repo.engine, reference_repo.engine)
        if not (engines[0] is engines[1] is engines[2]):
            raise ValueError(
                "real MySQL source management repositories must share one Engine"
            )
        return MysqlSourceMutationRepo(engines[0])

    @classmethod
    def _run_mutation(cls, action, *, map_duplicate: bool = False) -> None:
        try:
            action()
        except SourceMutationNotFoundError as exc:
            raise SourceNotFoundError(str(exc)) from exc
        except SourceMutationMustBeDisabledError as exc:
            raise SourceMustBeDisabledError(str(exc)) from exc
        except SourceMutationInUseError as exc:
            raise SourceInUseError(exc.job_names) from exc
        except SourceMutationRenameBlockedError as exc:
            raise SourceRenameBlockedError(exc.job_names) from exc
        except IntegrityError as exc:
            cls._raise_if_foreign_key_conflict(exc)
            if map_duplicate:
                cls._raise_if_duplicate(exc)
            raise
