from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.group_messages import GroupCursor, RawGroupMessage
from app.storage.source_mutation_repo import MysqlSourceWriteGuard


_SOURCE_WRITE_GUARD = MysqlSourceWriteGuard()


class GroupMessageRepo(Protocol):
    def insert_raw_ignore_duplicates(self, messages: list[RawGroupMessage]) -> int:
        ...

    def update_cursor(self, cursor: GroupCursor) -> None:
        ...


@dataclass(frozen=True)
class GroupConfigRecord:
    group_name: str
    priority: int
    poll_interval_seconds: int
    enabled: bool = True
    is_core_group: bool = True
    backtrack_pages: int = 10
    extra_backtrack_pages: int = 30
    remark: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class GroupCollectLogRecord:
    batch_id: str
    source_name: str
    start_time: datetime
    end_time: datetime | None
    status: str
    scan_pages: int = 0
    read_count: int = 0
    insert_count: int = 0
    duplicate_count: int = 0
    error_code: str | None = None
    error_msg: str | None = None
    screenshot_path: str | None = None


@dataclass(frozen=True)
class GroupRuntimeStatus:
    group_name: str
    enabled: bool
    is_core_group: bool
    priority: int
    poll_interval_seconds: int
    last_collect_batch_id: str | None
    last_success_collect_time: datetime | None
    consecutive_fail_count: int
    cursor_error_msg: str | None
    latest_log_status: str | None
    latest_log_read_count: int | None
    latest_log_insert_count: int | None
    latest_log_duplicate_count: int | None
    latest_log_error_code: str | None
    latest_log_screenshot_path: str | None
    ui_lock_owner_pipeline: str | None
    ui_lock_owner_task_id: str | None


class InMemoryGroupMessageRepo:
    def __init__(self) -> None:
        self.messages_by_hash: dict[str, RawGroupMessage] = {}
        self.cursor_by_group: dict[str, GroupCursor] = {}

    def insert_raw_ignore_duplicates(self, messages: list[RawGroupMessage]) -> int:
        inserted = 0
        for message in messages:
            if message.msg_hash in self.messages_by_hash:
                continue
            self.messages_by_hash[message.msg_hash] = message
            inserted += 1
        return inserted

    def update_cursor(self, cursor: GroupCursor) -> None:
        self.cursor_by_group[cursor.group_name] = cursor


class MysqlGroupMessageRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_raw_ignore_duplicates(self, messages: list[RawGroupMessage]) -> int:
        if not messages:
            return 0

        params = [
            {
                "msg_hash": message.msg_hash,
                "group_name": message.group_name,
                "sender_name": message.sender_name,
                "msg_time_display": message.msg_time_display,
                "msg_type": message.msg_type,
                "msg_content": message.msg_content,
                "raw_content": message.raw_content,
                "collect_time": message.collect_time,
                "collect_batch_id": message.collect_batch_id,
            }
            for message in messages
        ]

        statement = text(
            """
            INSERT IGNORE INTO wechat_group_msg_raw (
                msg_hash,
                group_name,
                sender_name,
                msg_time_display,
                msg_type,
                msg_content,
                raw_content,
                collect_time,
                collect_batch_id
            ) VALUES (
                :msg_hash,
                :group_name,
                :sender_name,
                :msg_time_display,
                :msg_type,
                :msg_content,
                :raw_content,
                :collect_time,
                :collect_batch_id
            )
            """
        )

        with self.engine.begin() as connection:
            for group_name in sorted({message.group_name for message in messages}):
                _SOURCE_WRITE_GUARD.lock_for_history_write(
                    connection, "group", group_name
                )
            result = connection.execute(statement, params)
            task_params = [
                {
                    "task_type": "clean_group_msg",
                    "ref_type": "msg",
                    "ref_id": message.msg_hash,
                }
                for message in messages
            ]
            connection.execute(
                text(
                    """
                    INSERT IGNORE INTO wechat_group_process_task (
                        task_type,
                        ref_type,
                        ref_id,
                        status
                    ) VALUES (
                        :task_type,
                        :ref_type,
                        :ref_id,
                        'pending'
                    )
                    """
                ),
                task_params,
            )
            return int(result.rowcount or 0)

    def update_cursor(self, cursor: GroupCursor) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_collect_cursor (
                group_name,
                last_msg_hash,
                last_msg_time_display,
                last_msg_content_preview,
                last_sender_name,
                last_success_collect_time,
                last_collect_batch_id,
                consecutive_fail_count,
                error_msg
            ) VALUES (
                :group_name,
                :last_msg_hash,
                :last_msg_time_display,
                :last_msg_content_preview,
                :last_sender_name,
                :last_success_collect_time,
                :last_collect_batch_id,
                0,
                NULL
            )
            ON DUPLICATE KEY UPDATE
                last_msg_hash = VALUES(last_msg_hash),
                last_msg_time_display = VALUES(last_msg_time_display),
                last_msg_content_preview = VALUES(last_msg_content_preview),
                last_sender_name = VALUES(last_sender_name),
                last_success_collect_time = VALUES(last_success_collect_time),
                last_collect_batch_id = VALUES(last_collect_batch_id),
                consecutive_fail_count = 0,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "group_name": cursor.group_name,
            "last_msg_hash": cursor.last_msg_hash,
            "last_msg_time_display": cursor.last_msg_time_display,
            "last_msg_content_preview": cursor.last_msg_content_preview,
            "last_sender_name": cursor.last_sender_name,
            "last_success_collect_time": cursor.last_success_collect_time,
            "last_collect_batch_id": cursor.last_collect_batch_id,
        }

        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "group", cursor.group_name
            )
            connection.execute(statement, params)


class MysqlGroupConfigRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert_group_config(
        self,
        *,
        group_name: str,
        enabled: bool,
        priority: int,
        poll_interval_seconds: int,
        backtrack_pages: int,
        extra_backtrack_pages: int,
        is_core_group: bool,
        remark: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_config (
                group_name,
                enabled,
                priority,
                poll_interval_seconds,
                backtrack_pages,
                extra_backtrack_pages,
                is_core_group,
                remark
            ) VALUES (
                :group_name,
                :enabled,
                :priority,
                :poll_interval_seconds,
                :backtrack_pages,
                :extra_backtrack_pages,
                :is_core_group,
                :remark
            )
            ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                priority = VALUES(priority),
                poll_interval_seconds = VALUES(poll_interval_seconds),
                backtrack_pages = VALUES(backtrack_pages),
                extra_backtrack_pages = VALUES(extra_backtrack_pages),
                is_core_group = VALUES(is_core_group),
                remark = VALUES(remark),
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "group_name": group_name,
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_seconds": poll_interval_seconds,
            "backtrack_pages": backtrack_pages,
            "extra_backtrack_pages": extra_backtrack_pages,
            "is_core_group": 1 if is_core_group else 0,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def create_group_config(
        self,
        *,
        group_name: str,
        enabled: bool,
        priority: int,
        poll_interval_seconds: int,
        backtrack_pages: int,
        extra_backtrack_pages: int,
        is_core_group: bool,
        remark: str | None,
    ) -> int:
        statement = text(
            """
            INSERT INTO wechat_group_config (
                group_name,
                enabled,
                priority,
                poll_interval_seconds,
                backtrack_pages,
                extra_backtrack_pages,
                is_core_group,
                remark
            ) VALUES (
                :group_name,
                :enabled,
                :priority,
                :poll_interval_seconds,
                :backtrack_pages,
                :extra_backtrack_pages,
                :is_core_group,
                :remark
            )
            """
        )
        params = {
            "group_name": group_name,
            "enabled": 1 if enabled else 0,
            "priority": priority,
            "poll_interval_seconds": poll_interval_seconds,
            "backtrack_pages": backtrack_pages,
            "extra_backtrack_pages": extra_backtrack_pages,
            "is_core_group": 1 if is_core_group else 0,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.lastrowid)

    def list_groups(self) -> list[GroupConfigRecord]:
        statement = text(
            """
            SELECT
                id,
                group_name,
                enabled,
                priority,
                poll_interval_seconds,
                backtrack_pages,
                extra_backtrack_pages,
                is_core_group,
                remark
            FROM wechat_group_config
            ORDER BY priority ASC, group_name ASC
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_from_row(row) for row in rows]

    def get_group(self, source_id: int) -> GroupConfigRecord | None:
        statement = text(
            """
            SELECT
                id,
                group_name,
                enabled,
                priority,
                poll_interval_seconds,
                backtrack_pages,
                extra_backtrack_pages,
                is_core_group,
                remark
            FROM wechat_group_config
            WHERE id = :source_id
            """
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement, {"source_id": source_id}).mappings().first()
        return None if row is None else self._record_from_row(row)

    def update_group_config(
        self,
        source_id: int,
        *,
        group_name: str,
        priority: int,
        poll_interval_seconds: int,
        backtrack_pages: int,
        extra_backtrack_pages: int,
        is_core_group: bool,
        remark: str | None,
    ) -> int:
        statement = text(
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
        params = {
            "source_id": source_id,
            "group_name": group_name,
            "priority": priority,
            "poll_interval_seconds": poll_interval_seconds,
            "backtrack_pages": backtrack_pages,
            "extra_backtrack_pages": extra_backtrack_pages,
            "is_core_group": 1 if is_core_group else 0,
            "remark": remark,
        }
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.rowcount or 0)

    def set_group_enabled(self, source_id: int, enabled: bool) -> int:
        statement = text(
            """
            UPDATE wechat_group_config
            SET enabled = :enabled,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :source_id
            """
        )
        params = {"source_id": source_id, "enabled": 1 if enabled else 0}
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
            return int(result.rowcount or 0)

    def delete_group(self, source_id: int) -> int:
        statement = text(
            """
            DELETE FROM wechat_group_config
            WHERE id = :source_id
              AND enabled = 0
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement, {"source_id": source_id})
            return int(result.rowcount or 0)

    def disable_group(self, group_name: str) -> None:
        statement = text(
            """
            UPDATE wechat_group_config
            SET enabled = 0,
                update_time = CURRENT_TIMESTAMP
            WHERE group_name = :group_name
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"group_name": group_name})

    def list_due_groups(self, now: datetime, limit: int) -> list[GroupConfigRecord]:
        statement = text(
            """
            SELECT
                cfg.id,
                cfg.group_name,
                cfg.priority,
                cfg.poll_interval_seconds
            FROM wechat_group_config cfg
            LEFT JOIN wechat_group_collect_cursor cur
              ON cur.group_name = cfg.group_name
            WHERE cfg.enabled = 1
              AND cfg.is_core_group = 1
              AND (
                cur.last_success_collect_time IS NULL
                OR TIMESTAMPDIFF(SECOND, cur.last_success_collect_time, :now) >= cfg.poll_interval_seconds
              )
            ORDER BY cfg.priority ASC, cur.last_success_collect_time ASC, cfg.group_name ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"now": now, "limit": limit}).mappings().all()
        return [
            self._record_from_row(row)
            for row in rows
        ]

    def _record_from_row(self, row) -> GroupConfigRecord:
        return GroupConfigRecord(
            group_name=str(row["group_name"]),
            priority=int(row["priority"]),
            poll_interval_seconds=int(row["poll_interval_seconds"]),
            enabled=bool(row.get("enabled", 1)),
            is_core_group=bool(row.get("is_core_group", 1)),
            backtrack_pages=int(row.get("backtrack_pages", 10)),
            extra_backtrack_pages=int(row.get("extra_backtrack_pages", 30)),
            remark=row.get("remark"),
            id=None if row.get("id") is None else int(row["id"]),
        )


class MysqlGroupCollectLogRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_collect_log(self, record: GroupCollectLogRecord) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_collect_log (
                batch_id,
                source_name,
                start_time,
                end_time,
                scan_pages,
                read_count,
                insert_count,
                duplicate_count,
                status,
                error_code,
                error_msg,
                screenshot_path
            ) VALUES (
                :batch_id,
                :source_name,
                :start_time,
                :end_time,
                :scan_pages,
                :read_count,
                :insert_count,
                :duplicate_count,
                :status,
                :error_code,
                :error_msg,
                :screenshot_path
            )
            """
        )
        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "group", record.source_name
            )
            connection.execute(statement, record.__dict__)

    def mark_group_collect_failed(self, group_name: str, error_msg: str) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_collect_cursor (
                group_name,
                consecutive_fail_count,
                error_msg
            ) VALUES (
                :group_name,
                1,
                :error_msg
            )
            ON DUPLICATE KEY UPDATE
                consecutive_fail_count = consecutive_fail_count + 1,
                error_msg = VALUES(error_msg),
                update_time = CURRENT_TIMESTAMP
            """
        )
        with self.engine.begin() as connection:
            _SOURCE_WRITE_GUARD.lock_for_history_write(
                connection, "group", group_name
            )
            connection.execute(statement, {"group_name": group_name, "error_msg": error_msg})


class MysqlGroupStatusRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_group_status(self, group_name: str) -> GroupRuntimeStatus | None:
        config_statement = text(
            """
            SELECT
                cfg.group_name,
                cfg.enabled,
                cfg.is_core_group,
                cfg.priority,
                cfg.poll_interval_seconds,
                cur.last_collect_batch_id,
                cur.last_success_collect_time,
                COALESCE(cur.consecutive_fail_count, 0) AS consecutive_fail_count,
                cur.error_msg
            FROM wechat_group_config cfg
            LEFT JOIN wechat_group_collect_cursor cur
              ON cur.group_name = cfg.group_name
            WHERE cfg.group_name = :group_name
            """
        )
        log_statement = text(
            """
            SELECT
                status,
                read_count,
                insert_count,
                duplicate_count,
                error_code,
                screenshot_path
            FROM wechat_group_collect_log
            WHERE source_name = :group_name
            ORDER BY id DESC
            LIMIT 1
            """
        )
        lock_statement = text(
            """
            SELECT
                owner_pipeline,
                owner_task_id
            FROM wechat_ui_lock
            WHERE lock_name = 'wechat_ui'
            LIMIT 1
            """
        )

        with self.engine.begin() as connection:
            config_row = connection.execute(config_statement, {"group_name": group_name}).mappings().first()
            if config_row is None:
                return None
            log_row = connection.execute(log_statement, {"group_name": group_name}).mappings().first()
            lock_row = connection.execute(lock_statement).mappings().first()

        return GroupRuntimeStatus(
            group_name=str(config_row["group_name"]),
            enabled=bool(config_row["enabled"]),
            is_core_group=bool(config_row["is_core_group"]),
            priority=int(config_row["priority"]),
            poll_interval_seconds=int(config_row["poll_interval_seconds"]),
            last_collect_batch_id=config_row["last_collect_batch_id"],
            last_success_collect_time=config_row["last_success_collect_time"],
            consecutive_fail_count=int(config_row["consecutive_fail_count"]),
            cursor_error_msg=config_row["error_msg"],
            latest_log_status=None if log_row is None else log_row["status"],
            latest_log_read_count=None if log_row is None else int(log_row["read_count"]),
            latest_log_insert_count=None if log_row is None else int(log_row["insert_count"]),
            latest_log_duplicate_count=None if log_row is None else int(log_row["duplicate_count"]),
            latest_log_error_code=None if log_row is None else log_row["error_code"],
            latest_log_screenshot_path=None if log_row is None else log_row["screenshot_path"],
            ui_lock_owner_pipeline=None if lock_row is None else lock_row["owner_pipeline"],
            ui_lock_owner_task_id=None if lock_row is None else lock_row["owner_task_id"],
        )
