from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


GROUP_TASK_REF_TYPES = {
    "clean_group_msg": "msg",
    "analyze_group_msg": "msg",
    "group_daily_report": "date",
}


@dataclass(frozen=True)
class GroupTaskRecord:
    id: int
    task_type: str
    ref_type: str
    ref_id: str
    status: str
    retry_count: int
    next_run_time: datetime | None
    error_msg: str | None
    update_time: datetime | None


@dataclass(frozen=True)
class GroupFailedTaskRecord:
    id: int
    task_type: str
    ref_type: str
    ref_id: str
    status: str
    retry_count: int
    next_run_time: datetime | None
    error_summary: str | None
    update_time: datetime | None


class MysqlGroupTaskAdminRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_tasks(
        self,
        task_type: str | None = None,
        status: str | None = None,
        ref_id: str | None = None,
        limit: int = 50,
    ) -> list[GroupTaskRecord]:
        filters = ["1 = 1"]
        params: dict[str, object] = {"limit": limit}
        if task_type:
            filters.append("task_type = :task_type")
            params["task_type"] = task_type
        if status:
            filters.append("status = :status")
            params["status"] = status
        if ref_id:
            filters.append("ref_id = :ref_id")
            params["ref_id"] = ref_id

        statement = text(
            f"""
            SELECT
                id,
                task_type,
                ref_type,
                ref_id,
                status,
                retry_count,
                next_run_time,
                error_msg,
                update_time
            FROM wechat_group_process_task
            WHERE {" AND ".join(filters)}
            ORDER BY update_time DESC, id DESC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()

        return [
            GroupTaskRecord(
                id=int(row["id"]),
                task_type=str(row["task_type"]),
                ref_type=str(row["ref_type"]),
                ref_id=str(row["ref_id"]),
                status=str(row["status"]),
                retry_count=int(row["retry_count"] or 0),
                next_run_time=row["next_run_time"],
                error_msg=row["error_msg"],
                update_time=row["update_time"],
            )
            for row in rows
        ]

    def list_failed_tasks(self, task_type: str | None = None, limit: int = 50) -> list[GroupFailedTaskRecord]:
        _validate_positive_limit(limit)
        if task_type:
            _ref_type_for_task(task_type)
        filters = ["status = 'failed'"]
        params: dict[str, object] = {"limit": limit}
        if task_type:
            filters.append("task_type = :task_type")
            params["task_type"] = task_type

        statement = text(
            f"""
            SELECT
                id,
                task_type,
                ref_type,
                ref_id,
                status,
                retry_count,
                next_run_time,
                LEFT(error_msg, 200) AS error_summary,
                update_time
            FROM wechat_group_process_task
            WHERE {" AND ".join(filters)}
            ORDER BY update_time DESC, id DESC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()

        return [
            GroupFailedTaskRecord(
                id=int(row["id"]),
                task_type=str(row["task_type"]),
                ref_type=str(row["ref_type"]),
                ref_id=str(row["ref_id"]),
                status=str(row["status"]),
                retry_count=int(row["retry_count"] or 0),
                next_run_time=row["next_run_time"],
                error_summary=row["error_summary"],
                update_time=row["update_time"],
            )
            for row in rows
        ]

    def retry_failed_tasks(self, task_type: str | None = None, limit: int = 50) -> int:
        _validate_positive_limit(limit)
        if task_type:
            _ref_type_for_task(task_type)
        filters = ["status = 'failed'"]
        params: dict[str, object] = {"limit": limit}
        if task_type:
            filters.append("task_type = :task_type")
            params["task_type"] = task_type

        statement = text(
            f"""
            UPDATE wechat_group_process_task
            SET status = 'pending',
                retry_count = 0,
                next_run_time = NULL,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE {" AND ".join(filters)}
            ORDER BY update_time ASC, id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement, params)
        return int(result.rowcount or 0)

    def reset_task(self, task_type: str, ref_id: str) -> int:
        ref_type = _ref_type_for_task(task_type)
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = 'pending',
                retry_count = 0,
                next_run_time = NULL,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = :task_type
              AND ref_type = :ref_type
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {"task_type": task_type, "ref_type": ref_type, "ref_id": ref_id},
            )
        return int(result.rowcount or 0)

    def reset_daily_report_date(self, report_date: date) -> int:
        statement = text(
            """
            INSERT INTO wechat_group_process_task (
                task_type,
                ref_type,
                ref_id,
                status,
                retry_count
            ) VALUES (
                :task_type,
                :ref_type,
                :ref_id,
                'pending',
                0
            )
            ON DUPLICATE KEY UPDATE
                status = 'pending',
                retry_count = 0,
                next_run_time = NULL,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {
                    "task_type": "group_daily_report",
                    "ref_type": "date",
                    "ref_id": report_date.isoformat(),
                },
            )
        return int(result.rowcount or 0)


def _ref_type_for_task(task_type: str) -> str:
    try:
        return GROUP_TASK_REF_TYPES[task_type]
    except KeyError as exc:
        raise ValueError(f"unsupported group task_type: {task_type}") from exc


def _validate_positive_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
