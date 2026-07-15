from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.domain.group_analysis import (
    AnalyzedGroupMessage,
    DailyReportDraft,
    DailyReportStats,
    analyze_clean_group_message,
    build_group_daily_report,
)
from app.domain.group_analysis_rules import AnalysisRuleSet, DEFAULT_ANALYSIS_RULE_SET
from app.domain.group_cleaning import CleanGroupMessage
from app.domain.report_lifecycle import ReportLifecycle


@dataclass(frozen=True)
class GroupAnalysisResult:
    read_count: int
    success_count: int
    failed_count: int


@dataclass(frozen=True)
class GroupDailyReportResult:
    report_date: date
    generated_count: int


class GroupAnalysisRepo(Protocol):
    def list_pending_analyze_clean_messages(self, limit: int) -> list[CleanGroupMessage]:
        ...

    def upsert_message_analysis(self, analysis: AnalyzedGroupMessage) -> None:
        ...

    def create_daily_report_task(self, report_date: date) -> None:
        ...

    def mark_analyze_task_success(self, msg_hash: str) -> None:
        ...

    def mark_analyze_task_failed(self, msg_hash: str, error_msg: str) -> None:
        ...


class GroupDailyReportRepo(Protocol):
    def list_daily_report_stats(self, report_date: date, group_name: str | None) -> list[DailyReportStats]:
        ...

    def upsert_daily_report(self, report: DailyReportDraft, lifecycle: ReportLifecycle) -> None:
        ...

    def mark_daily_report_task_success(self, report_date: date) -> None:
        ...


class GroupAnalysisService:
    def __init__(self, *, repo: GroupAnalysisRepo, rule_set: AnalysisRuleSet | None = None) -> None:
        self.repo = repo
        self.rule_set = rule_set or DEFAULT_ANALYSIS_RULE_SET

    def analyze_once(self, limit: int, analyze_time: datetime) -> GroupAnalysisResult:
        clean_messages = self.repo.list_pending_analyze_clean_messages(limit)
        success_count = 0
        failed_count = 0

        for message in clean_messages:
            try:
                analysis = analyze_clean_group_message(
                    message,
                    analyze_time=analyze_time,
                    rule_set=self.rule_set,
                )
                self.repo.upsert_message_analysis(analysis)
                self.repo.create_daily_report_task(analysis.activity_date)
                self.repo.mark_analyze_task_success(message.msg_hash)
                success_count += 1
            except Exception as exc:
                self.repo.mark_analyze_task_failed(message.msg_hash, str(exc))
                failed_count += 1

        return GroupAnalysisResult(
            read_count=len(clean_messages),
            success_count=success_count,
            failed_count=failed_count,
        )


class GroupDailyReportService:
    def __init__(self, *, repo: GroupDailyReportRepo) -> None:
        self.repo = repo

    def generate_once(
        self,
        *,
        report_date: date,
        group_name: str | None,
        generate_time: datetime,
        lifecycle: ReportLifecycle,
    ) -> GroupDailyReportResult:
        stats_rows = self.repo.list_daily_report_stats(report_date=report_date, group_name=group_name)
        for stats in stats_rows:
            report = build_group_daily_report(stats, generate_time=generate_time)
            self.repo.upsert_daily_report(report, lifecycle)
        if group_name is None:
            self.repo.mark_daily_report_task_success(report_date)
        return GroupDailyReportResult(report_date=report_date, generated_count=len(stats_rows))
