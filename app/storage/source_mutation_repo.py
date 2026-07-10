from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.storage.source_reference_repo import list_referencing_jobs_on_connection


class SourceMutationNotFoundError(LookupError):
    pass


class SourceMutationMustBeDisabledError(RuntimeError):
    pass


class SourceMutationInUseError(RuntimeError):
    def __init__(self, job_names: list[str]) -> None:
        self.job_names = tuple(job_names)
        super().__init__("source is referenced by collection jobs")


class SourceMutationRenameBlockedError(RuntimeError):
    def __init__(self, job_names: list[str]) -> None:
        self.job_names = tuple(job_names)
        super().__init__("source has history or task references")


class SourceGuardNotFoundError(LookupError):
    pass


class SourceGuardDisabledError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceGuardRecord:
    id: int
    source_name: str
    enabled: bool


class MysqlSourceWriteGuard:
    """Locks source identity inside the caller's existing write transaction."""

    def lock_for_job_target(
        self, connection: Connection, source_type: str, source_id: int
    ) -> SourceGuardRecord:
        statement = _source_lock_statement(source_type, by_name=False, for_update=False)
        row = connection.execute(
            statement, {"source_id": source_id}
        ).mappings().first()
        record = _guard_record(row, source_type, str(source_id))
        if not record.enabled:
            raise SourceGuardDisabledError(
                f"{source_type} source is disabled: {source_id}"
            )
        return record

    def lock_for_history_write(
        self, connection: Connection, source_type: str, source_name: str
    ) -> SourceGuardRecord:
        statement = _source_lock_statement(source_type, by_name=True, for_update=False)
        row = connection.execute(
            statement, {"source_name": source_name}
        ).mappings().first()
        return _guard_record(row, source_type, source_name)

    def lock_for_history_and_config_update(
        self, connection: Connection, source_type: str, source_name: str
    ) -> SourceGuardRecord:
        """Locks identity exclusively when the same transaction updates config."""
        statement = _source_lock_statement(source_type, by_name=True, for_update=True)
        row = connection.execute(
            statement, {"source_name": source_name}
        ).mappings().first()
        return _guard_record(row, source_type, source_name)


class MysqlSourceMutationRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def update_group(self, source_id: int, **values) -> None:
        with self.engine.begin() as connection:
            current = self._lock_source(connection, "group", source_id)
            new_name = str(values["group_name"])
            if new_name != current.source_name:
                jobs = list_referencing_jobs_on_connection(
                    connection,
                    "group",
                    source_id,
                    active_only=False,
                    lock_rows=True,
                )
                if jobs or _has_current_history(
                    connection, "group", current.source_name
                ):
                    raise SourceMutationRenameBlockedError(jobs)
            connection.execute(
                _UPDATE_GROUP_STATEMENT,
                {
                    "source_id": source_id,
                    **values,
                    "is_core_group": 1 if values["is_core_group"] else 0,
                },
            )

    def update_article(self, source_id: int, **values) -> None:
        with self.engine.begin() as connection:
            current = self._lock_source(connection, "article", source_id)
            new_name = str(values["account_name"])
            if new_name != current.source_name:
                jobs = list_referencing_jobs_on_connection(
                    connection,
                    "article",
                    source_id,
                    active_only=False,
                    lock_rows=True,
                )
                if jobs or _has_current_history(
                    connection, "article", current.source_name
                ):
                    raise SourceMutationRenameBlockedError(jobs)
            connection.execute(
                _UPDATE_ARTICLE_STATEMENT,
                {
                    "source_id": source_id,
                    **values,
                    "collect_today_only": 1 if values["collect_today_only"] else 0,
                },
            )

    def set_group_enabled(self, source_id: int, enabled: bool) -> None:
        self._set_enabled("group", source_id, enabled)

    def set_article_enabled(self, source_id: int, enabled: bool) -> None:
        self._set_enabled("article", source_id, enabled)

    def delete_group(self, source_id: int) -> None:
        self._delete("group", source_id)

    def delete_article(self, source_id: int) -> None:
        self._delete("article", source_id)

    def _set_enabled(self, source_type: str, source_id: int, enabled: bool) -> None:
        with self.engine.begin() as connection:
            current = self._lock_source(connection, source_type, source_id)
            if current.enabled == enabled:
                return
            if not enabled:
                jobs = list_referencing_jobs_on_connection(
                    connection,
                    source_type,
                    source_id,
                    active_only=True,
                    lock_rows=True,
                )
                if jobs:
                    raise SourceMutationInUseError(jobs)
            table = _source_table(source_type)
            connection.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET enabled = :enabled,
                        update_time = CURRENT_TIMESTAMP
                    WHERE id = :source_id
                    """
                ),
                {"source_id": source_id, "enabled": 1 if enabled else 0},
            )

    def _delete(self, source_type: str, source_id: int) -> None:
        with self.engine.begin() as connection:
            current = self._lock_source(connection, source_type, source_id)
            if current.enabled:
                raise SourceMutationMustBeDisabledError(
                    f"{source_type} source must be disabled"
                )
            jobs = list_referencing_jobs_on_connection(
                connection,
                source_type,
                source_id,
                active_only=False,
                lock_rows=True,
            )
            if jobs:
                raise SourceMutationInUseError(jobs)
            table = _source_table(source_type)
            connection.execute(
                text(
                    f"""
                    DELETE FROM {table}
                    WHERE id = :source_id
                      AND enabled = 0
                    """
                ),
                {"source_id": source_id},
            )

    @staticmethod
    def _lock_source(
        connection: Connection, source_type: str, source_id: int
    ) -> SourceGuardRecord:
        statement = _source_lock_statement(source_type, by_name=False, for_update=True)
        row = connection.execute(
            statement, {"source_id": source_id}
        ).mappings().first()
        if row is None:
            raise SourceMutationNotFoundError(
                f"{source_type} source not found: {source_id}"
            )
        return SourceGuardRecord(
            id=int(row["id"]),
            source_name=str(row["source_name"]),
            enabled=bool(row["enabled"]),
        )


def _guard_record(row, source_type: str, source_identity: str) -> SourceGuardRecord:
    if row is None:
        raise SourceGuardNotFoundError(
            f"{source_type} source not found: {source_identity}"
        )
    return SourceGuardRecord(
        id=int(row["id"]),
        source_name=str(row["source_name"]),
        enabled=bool(row["enabled"]),
    )


def _source_lock_statement(source_type: str, *, by_name: bool, for_update: bool):
    if source_type == "group":
        table = "wechat_group_config"
        name_column = "group_name"
    elif source_type == "article":
        table = "wechat_public_account_config"
        name_column = "account_name"
    else:
        raise ValueError("source_type must be group or article")
    predicate = (
        f"{name_column} = :source_name" if by_name else "id = :source_id"
    )
    lock_clause = "FOR UPDATE" if for_update else "FOR SHARE"
    return text(
        f"""
        SELECT
            id,
            {name_column} AS source_name,
            enabled
        FROM {table}
        WHERE {predicate}
        {lock_clause}
        """
    )


def _source_table(source_type: str) -> str:
    if source_type == "group":
        return "wechat_group_config"
    if source_type == "article":
        return "wechat_public_account_config"
    raise ValueError("source_type must be group or article")


def _has_current_history(
    connection: Connection, source_type: str, source_name: str
) -> bool:
    if source_type == "group":
        history_sources = (
            ("wechat_group_msg_raw", "group_name"),
            ("wechat_group_msg_clean", "group_name"),
            ("wechat_group_msg_analysis", "group_name"),
            ("wechat_group_daily_report", "group_name"),
            ("wechat_group_collect_cursor", "group_name"),
            ("wechat_group_collect_log", "source_name"),
        )
    elif source_type == "article":
        history_sources = (
            ("wechat_article_route_cache", "account_name"),
            ("wechat_article_raw", "account_name"),
            ("wechat_article_clean", "account_name"),
            ("wechat_article_analysis", "account_name"),
            ("wechat_article_egg_price_item", "account_name"),
            ("wechat_article_daily_report", "account_name"),
            ("wechat_article_collect_log", "account_name"),
            ("wechat_article_collect_progress", "account_name"),
        )
    else:
        raise ValueError("source_type must be group or article")

    for table, column in history_sources:
        row = connection.execute(
            text(
                f"""
                SELECT 1
                FROM {table}
                WHERE {column} = :source_name
                LIMIT 1
                FOR SHARE
                """
            ),
            {"source_name": source_name},
        ).first()
        if row is not None:
            return True
    return False


_UPDATE_GROUP_STATEMENT = text(
    """
    UPDATE wechat_group_config
    SET group_name = :group_name,
        priority = :priority,
        poll_interval_seconds = :poll_interval_seconds,
        backtrack_pages = :backtrack_pages,
        extra_backtrack_pages = :extra_backtrack_pages,
        is_core_group = :is_core_group,
        remark = :remark,
        update_time = CURRENT_TIMESTAMP
    WHERE id = :source_id
    """
)


_UPDATE_ARTICLE_STATEMENT = text(
    """
    UPDATE wechat_public_account_config
    SET account_name = :account_name,
        account_type = :account_type,
        priority = :priority,
        poll_interval_minutes = :poll_interval_minutes,
        daily_window_start = :daily_window_start,
        daily_window_end = :daily_window_end,
        max_articles_per_round = :max_articles_per_round,
        collect_today_only = :collect_today_only,
        remark = :remark,
        update_time = CURRENT_TIMESTAMP
    WHERE id = :source_id
    """
)
