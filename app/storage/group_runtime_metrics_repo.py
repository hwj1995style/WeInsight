from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.storage.group_runtime_summary_repo import GroupTaskBacklogSummary


@dataclass(frozen=True)
class GroupRuntimeMetrics:
    window_hours: int
    collect_success_count: int
    collect_failed_count: int
    collect_total_count: int
    collect_failure_rate: float
    daily_report_count: int
    task_backlogs: list[GroupTaskBacklogSummary]


class MysqlGroupRuntimeMetricsRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_metrics(self, hours: int) -> GroupRuntimeMetrics:
        if hours <= 0:
            raise ValueError("hours must be greater than 0")

        with self.engine.begin() as connection:
            collect_row = connection.execute(_collect_metrics_statement(), {"hours": hours}).mappings().one()
            task_rows = connection.execute(_task_backlog_statement()).mappings().all()
            report_row = connection.execute(_daily_report_count_statement(), {"hours": hours}).mappings().one()

        success_count = int(collect_row["collect_success_count"] or 0)
        failed_count = int(collect_row["collect_failed_count"] or 0)
        total_count = success_count + failed_count
        failure_rate = 0.0 if total_count == 0 else failed_count / total_count
        return GroupRuntimeMetrics(
            window_hours=hours,
            collect_success_count=success_count,
            collect_failed_count=failed_count,
            collect_total_count=total_count,
            collect_failure_rate=failure_rate,
            daily_report_count=int(report_row["daily_report_count"] or 0),
            task_backlogs=[
                GroupTaskBacklogSummary(
                    task_type=str(row["task_type"]),
                    status=str(row["status"]),
                    count=int(row["cnt"]),
                )
                for row in task_rows
            ],
        )


def _collect_metrics_statement():
    return text(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS collect_success_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS collect_failed_count
        FROM wechat_group_collect_log
        WHERE start_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)
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
        WHERE status IN ('pending', 'running', 'failed')
        GROUP BY task_type, status
        ORDER BY task_type ASC, status ASC
        """
    )


def _daily_report_count_statement():
    return text(
        """
        SELECT
            COUNT(*) AS daily_report_count
        FROM wechat_group_daily_report
        WHERE generate_time >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL :hours HOUR)
        """
    )
