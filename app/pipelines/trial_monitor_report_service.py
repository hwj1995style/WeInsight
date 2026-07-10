from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.trial_monitor_report import TrialMonitorReport, build_trial_monitor_report


class RuntimeMetricsRepo(Protocol):
    def get_metrics(self, hours: int):
        ...


class TrialMonitorReportService:
    def __init__(self, *, group_metrics_repo: RuntimeMetricsRepo, article_metrics_repo: RuntimeMetricsRepo) -> None:
        self.group_metrics_repo = group_metrics_repo
        self.article_metrics_repo = article_metrics_repo

    def generate(self, *, hours: int, generate_time: datetime) -> TrialMonitorReport:
        group_metrics = self.group_metrics_repo.get_metrics(hours)
        article_metrics = self.article_metrics_repo.get_metrics(hours)
        return build_trial_monitor_report(
            hours=hours,
            group_success_count=int(group_metrics.collect_success_count),
            group_failed_count=int(group_metrics.collect_failed_count),
            group_backlog_count=_sum_backlog_count(group_metrics.task_backlogs),
            article_success_count=int(article_metrics.collect_success_count),
            article_failed_count=int(article_metrics.collect_failed_count),
            article_backlog_count=_sum_backlog_count(article_metrics.task_backlogs),
            ui_lock_timeout_count=0,
            generate_time=generate_time,
        )


def _sum_backlog_count(backlogs) -> int:
    return sum(int(backlog.count) for backlog in backlogs)
