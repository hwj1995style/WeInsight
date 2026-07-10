from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from app.domain.report_lifecycle import GenerationTrigger, ReportStatus


@dataclass(frozen=True)
class ArticleDailyReportSummary:
    report_date: date
    account_name: str
    title: str
    article_count: int
    avg_content_length: int
    generate_time: datetime
    report_status: ReportStatus
    data_cutoff_time: datetime
    generation_trigger: GenerationTrigger
    last_generated_by: str


@dataclass(frozen=True)
class ArticleDailyReportDetail:
    report_date: date
    account_name: str
    title: str
    markdown_body: str
    article_count: int
    avg_content_length: int
    top_tags_json: str
    top_keywords_json: str
    report_version: str
    generate_time: datetime
    report_status: ReportStatus
    data_cutoff_time: datetime
    generation_trigger: GenerationTrigger
    last_generated_by: str


@dataclass(frozen=True)
class ArticleDailyReportExportResult:
    export_path: Path
    bytes_written: int


class ArticleDailyReportNotFoundError(Exception):
    pass


class ArticleDailyReportQueryRepo(Protocol):
    def list_daily_reports(
        self,
        report_date: date,
        account_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[ArticleDailyReportSummary]:
        ...

    def get_daily_report(self, report_date: date, account_name: str) -> ArticleDailyReportDetail | None:
        ...


class ArticleDailyReportQueryService:
    def __init__(
        self,
        *,
        repo: ArticleDailyReportQueryRepo,
        export_root: Path = Path("runtime/reports/article"),
    ) -> None:
        self.repo = repo
        self.export_root = export_root

    def list_reports(
        self,
        report_date: date,
        account_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[ArticleDailyReportSummary]:
        if offset == 0:
            return self.repo.list_daily_reports(
                report_date=report_date,
                account_name=account_name,
                limit=limit,
            )
        return self.repo.list_daily_reports(
            report_date=report_date,
            account_name=account_name,
            limit=limit,
            offset=offset,
        )

    def get_report(self, report_date: date, account_name: str) -> ArticleDailyReportDetail | None:
        return self.repo.get_daily_report(report_date=report_date, account_name=account_name)

    def export_report(
        self,
        report_date: date,
        account_name: str,
        output_path: Path | None = None,
    ) -> ArticleDailyReportExportResult:
        report = self.get_report(report_date=report_date, account_name=account_name)
        if report is None:
            raise ArticleDailyReportNotFoundError(
                f"article daily report not found: {report_date.isoformat()} {account_name}"
            )

        export_path = _resolve_export_path(output_path or self.export_root, report)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.markdown_body
        export_path.write_text(payload, encoding="utf-8")
        return ArticleDailyReportExportResult(
            export_path=export_path,
            bytes_written=len(payload.encode("utf-8")),
        )


def _resolve_export_path(output_path: Path, report: ArticleDailyReportDetail) -> Path:
    if output_path.suffix.lower() == ".md":
        return output_path
    safe_account_name = _safe_filename(report.account_name)
    return output_path / report.report_date.isoformat() / f"{safe_account_name}.md"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", value).strip().strip(".")
    return cleaned or "article"
