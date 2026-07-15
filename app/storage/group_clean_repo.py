from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.group_cleaning import CleanGroupMessage
from app.domain.group_messages import RawGroupMessage


class MysqlGroupCleanRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_pending_clean_raw_messages(self, limit: int) -> list[RawGroupMessage]:
        statement = text(
            """
            SELECT
                raw.msg_hash,
                raw.group_name,
                raw.sender_name,
                raw.msg_time_display,
                raw.msg_type,
                raw.msg_content,
                raw.raw_content,
                raw.collect_time,
                raw.collect_batch_id
            FROM wechat_group_process_task task
            JOIN wechat_group_msg_raw raw
              ON raw.msg_hash = task.ref_id
            WHERE task.task_type = 'clean_group_msg'
              AND task.ref_type = 'msg'
              AND task.status = 'pending'
              AND (task.next_run_time IS NULL OR task.next_run_time <= CURRENT_TIMESTAMP)
            ORDER BY task.create_time ASC, task.id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings().all()

        return [
            RawGroupMessage(
                msg_hash=str(row["msg_hash"]),
                group_name=str(row["group_name"]),
                sender_name=str(row["sender_name"] or ""),
                msg_time_display=str(row["msg_time_display"] or ""),
                msg_type=str(row["msg_type"] or "text"),
                msg_content=str(row["msg_content"] or ""),
                raw_content=str(row["raw_content"] or ""),
                collect_time=row["collect_time"],
                collect_batch_id=str(row["collect_batch_id"] or ""),
            )
            for row in rows
        ]

    def upsert_clean_message(self, message: CleanGroupMessage) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_msg_clean (
                msg_hash,
                group_name,
                sender_hash,
                sender_display,
                msg_time_display,
                msg_time_inferred,
                msg_type,
                clean_content,
                content_length,
                is_empty,
                has_phone,
                has_wechat_id,
                clean_version,
                source_collect_batch_id,
                clean_time
            ) VALUES (
                :msg_hash,
                :group_name,
                :sender_hash,
                :sender_display,
                :msg_time_display,
                :msg_time_inferred,
                :msg_type,
                :clean_content,
                :content_length,
                :is_empty,
                :has_phone,
                :has_wechat_id,
                :clean_version,
                :source_collect_batch_id,
                :clean_time
            )
            ON DUPLICATE KEY UPDATE
                group_name = VALUES(group_name),
                sender_hash = VALUES(sender_hash),
                sender_display = VALUES(sender_display),
                msg_time_display = VALUES(msg_time_display),
                msg_time_inferred = VALUES(msg_time_inferred),
                msg_type = VALUES(msg_type),
                clean_content = VALUES(clean_content),
                content_length = VALUES(content_length),
                is_empty = VALUES(is_empty),
                has_phone = VALUES(has_phone),
                has_wechat_id = VALUES(has_wechat_id),
                clean_version = VALUES(clean_version),
                source_collect_batch_id = VALUES(source_collect_batch_id),
                clean_time = VALUES(clean_time)
            """
        )
        params = {
            "msg_hash": message.msg_hash,
            "group_name": message.group_name,
            "sender_hash": message.sender_hash,
            "sender_display": message.sender_display,
            "msg_time_display": message.msg_time_display,
            "msg_time_inferred": message.msg_time_inferred,
            "msg_type": message.msg_type,
            "clean_content": message.clean_content,
            "content_length": message.content_length,
            "is_empty": 1 if message.is_empty else 0,
            "has_phone": 1 if message.has_phone else 0,
            "has_wechat_id": 1 if message.has_wechat_id else 0,
            "clean_version": message.clean_version,
            "source_collect_batch_id": message.source_collect_batch_id,
            "clean_time": message.clean_time,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def create_analyze_task(self, msg_hash: str) -> None:
        statement = text(
            """
            INSERT IGNORE INTO wechat_group_process_task (
                task_type,
                ref_type,
                ref_id,
                status
            ) VALUES (
                :task_type,
                'msg',
                :ref_id,
                'pending'
            )
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"task_type": "analyze_group_msg", "ref_id": msg_hash})

    def mark_clean_task_success(self, msg_hash: str) -> None:
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'clean_group_msg'
              AND ref_type = 'msg'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": msg_hash})

    def mark_clean_task_failed(self, msg_hash: str, error_msg: str) -> None:
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = CASE WHEN retry_count + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                retry_count = retry_count + 1,
                next_run_time = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 60 SECOND),
                error_msg = :error_msg,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'clean_group_msg'
              AND ref_type = 'msg'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": msg_hash, "error_msg": error_msg})
