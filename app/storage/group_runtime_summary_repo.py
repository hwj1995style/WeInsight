from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class GroupConfigSummary:
    total_count: int
    enabled_count: int
    core_enabled_count: int


@dataclass(frozen=True)
class GroupTaskBacklogSummary:
    task_type: str
    status: str
    count: int


@dataclass(frozen=True)
class UiLockRuntimeSummary:
    status: str
    owner_pipeline: str | None
    owner_task_id: str | None
    expire_time: datetime | None


@dataclass(frozen=True)
class LatestGroupCollectLogSummary:
    source_name: str
    batch_id: str
    status: str
    start_time: datetime | None
    end_time: datetime | None
    read_count: int
    insert_count: int
    duplicate_count: int
    error_code: str | None
    screenshot_path: str | None


@dataclass(frozen=True)
class GroupRuntimeSummary:
    config: GroupConfigSummary
    ui_lock: UiLockRuntimeSummary
    task_backlogs: list[GroupTaskBacklogSummary]
    latest_collect_logs: list[LatestGroupCollectLogSummary]


class MysqlGroupRuntimeSummaryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_summary(self, limit: int) -> GroupRuntimeSummary:
        with self.engine.begin() as connection:
            config_row = connection.execute(_config_summary_statement()).mappings().one()
            task_rows = connection.execute(_task_backlog_statement()).mappings().all()
            lock_row = connection.execute(_ui_lock_statement()).mappings().first()
            log_rows = connection.execute(_latest_collect_logs_statement(), {"limit": limit}).mappings().all()

        return GroupRuntimeSummary(
            config=GroupConfigSummary(
                total_count=int(config_row["total_count"] or 0),
                enabled_count=int(config_row["enabled_count"] or 0),
                core_enabled_count=int(config_row["core_enabled_count"] or 0),
            ),
            ui_lock=_lock_summary(lock_row),
            task_backlogs=[
                GroupTaskBacklogSummary(
                    task_type=str(row["task_type"]),
                    status=str(row["status"]),
                    count=int(row["cnt"]),
                )
                for row in task_rows
            ],
            latest_collect_logs=[
                LatestGroupCollectLogSummary(
                    source_name=str(row["source_name"]),
                    batch_id=str(row["batch_id"]),
                    status=str(row["status"]),
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    read_count=int(row["read_count"] or 0),
                    insert_count=int(row["insert_count"] or 0),
                    duplicate_count=int(row["duplicate_count"] or 0),
                    error_code=row["error_code"],
                    screenshot_path=row["screenshot_path"],
                )
                for row in log_rows
            ],
        )


def _config_summary_statement():
    return text(
        """
        SELECT
            COUNT(*) AS total_count,
            COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_count,
            COALESCE(SUM(CASE WHEN enabled = 1 AND is_core_group = 1 THEN 1 ELSE 0 END), 0) AS core_enabled_count
        FROM wechat_group_config
        """
    )


def _task_backlog_statement():
    return text(
        """
        SELECT
            task_type,
            status,
            COUNT(*) AS cnt
        FROM wechat_group_process_task
        GROUP BY task_type, status
        ORDER BY task_type ASC, status ASC
        """
    )


def _ui_lock_statement():
    return text(
        """
        SELECT
            owner_pipeline,
            owner_task_id,
            expire_time
        FROM wechat_ui_lock
        WHERE lock_name = 'wechat_ui'
        LIMIT 1
        """
    )


def _latest_collect_logs_statement():
    return text(
        """
        SELECT
            log.source_name,
            log.batch_id,
            log.status,
            log.start_time,
            log.end_time,
            log.read_count,
            log.insert_count,
            log.duplicate_count,
            log.error_code,
            log.screenshot_path
        FROM wechat_group_collect_log log
        JOIN (
            SELECT
                source_name,
                MAX(id) AS latest_id
            FROM wechat_group_collect_log
            GROUP BY source_name
        ) latest
          ON latest.latest_id = log.id
        ORDER BY log.source_name ASC
        LIMIT :limit
        """
    )


def _lock_summary(row) -> UiLockRuntimeSummary:
    if row is None:
        return UiLockRuntimeSummary(
            status="free",
            owner_pipeline=None,
            owner_task_id=None,
            expire_time=None,
        )
    return UiLockRuntimeSummary(
        status="held",
        owner_pipeline=row["owner_pipeline"],
        owner_task_id=row["owner_task_id"],
        expire_time=row["expire_time"],
    )
