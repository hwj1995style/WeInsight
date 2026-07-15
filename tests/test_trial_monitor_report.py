from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.trial_monitor_report import build_trial_monitor_report
from app.pipelines.trial_monitor_report_service import TrialMonitorReportService


def test_build_trial_monitor_report_summarizes_two_link_metrics() -> None:
    report = build_trial_monitor_report(
        hours=24,
        group_success_count=10,
        group_failed_count=1,
        group_backlog_count=2,
        article_success_count=8,
        article_failed_count=1,
        article_backlog_count=3,
        ui_lock_timeout_count=0,
        generate_time=datetime(2026, 7, 7, 18, 0),
    )

    assert report.hours == 24
    assert report.group_success_count == 10
    assert report.group_failed_count == 1
    assert report.group_backlog_count == 2
    assert report.article_success_count == 8
    assert report.article_failed_count == 1
    assert report.article_backlog_count == 3
    assert report.ui_lock_timeout_count == 0
    assert "群链路成功数：10" in report.markdown_body
    assert "群链路失败数：1" in report.markdown_body
    assert "群链路积压数：2" in report.markdown_body
    assert "article 链路成功数：8" in report.markdown_body
    assert "article 链路失败数：1" in report.markdown_body
    assert "article 链路积压数：3" in report.markdown_body
    assert "UI 锁超时数：0" in report.markdown_body
    assert "raw_content" not in report.markdown_body
    assert "clean_content" not in report.markdown_body
    assert "markdown_body" not in report.markdown_body
    assert "article_url" not in report.markdown_body


def test_trial_monitor_report_service_reads_two_metric_repos() -> None:
    group_repo = FakeGroupMetricsRepo()
    article_repo = FakeArticleMetricsRepo()
    service = TrialMonitorReportService(group_metrics_repo=group_repo, article_metrics_repo=article_repo)

    report = service.generate(hours=12, generate_time=datetime(2026, 7, 7, 18, 0))

    assert report.hours == 12
    assert report.group_success_count == 6
    assert report.group_failed_count == 2
    assert report.group_backlog_count == 4
    assert report.article_success_count == 7
    assert report.article_failed_count == 1
    assert report.article_backlog_count == 5
    assert group_repo.calls == [12]
    assert article_repo.calls == [12]


@dataclass(frozen=True)
class FakeBacklog:
    task_type: str
    status: str
    count: int


@dataclass(frozen=True)
class FakeGroupMetrics:
    window_hours: int
    collect_success_count: int
    collect_failed_count: int
    collect_total_count: int
    collect_failure_rate: float
    daily_report_count: int
    task_backlogs: list[FakeBacklog]


@dataclass(frozen=True)
class FakeArticleMetrics:
    window_hours: int
    account_total_count: int
    account_enabled_count: int
    collect_success_count: int
    collect_failed_count: int
    collect_skipped_count: int
    collect_total_count: int
    latest_error_summary: str | None
    task_backlogs: list[FakeBacklog]


class FakeGroupMetricsRepo:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_metrics(self, hours: int) -> FakeGroupMetrics:
        self.calls.append(hours)
        return FakeGroupMetrics(
            window_hours=hours,
            collect_success_count=6,
            collect_failed_count=2,
            collect_total_count=8,
            collect_failure_rate=0.25,
            daily_report_count=1,
            task_backlogs=[
                FakeBacklog(task_type="clean_group_msg", status="pending", count=3),
                FakeBacklog(task_type="analyze_group_msg", status="failed", count=1),
            ],
        )


class FakeArticleMetricsRepo:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_metrics(self, hours: int) -> FakeArticleMetrics:
        self.calls.append(hours)
        return FakeArticleMetrics(
            window_hours=hours,
            account_total_count=20,
            account_enabled_count=3,
            collect_success_count=7,
            collect_failed_count=1,
            collect_skipped_count=2,
            collect_total_count=10,
            latest_error_summary=None,
            task_backlogs=[
                FakeBacklog(task_type="clean_article", status="pending", count=4),
                FakeBacklog(task_type="analyze_article", status="failed", count=1),
            ],
        )
