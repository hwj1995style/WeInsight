from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from app.domain.group_reports import DailyReportDetail, DailyReportSummary


@dataclass(frozen=True)
class DailyReportExportResult:
    export_path: Path
    bytes_written: int


class DailyReportNotFoundError(Exception):
    pass


class GroupDailyReportQueryRepo(Protocol):
    def list_daily_reports(
        self,
        report_date: date,
        group_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[DailyReportSummary]:
        ...

    def get_daily_report(self, report_date: date, group_name: str) -> DailyReportDetail | None:
        ...


class GroupDailyReportQueryService:
    def __init__(self, *, repo: GroupDailyReportQueryRepo) -> None:
        self.repo = repo

    def list_reports(
        self,
        report_date: date,
        group_name: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[DailyReportSummary]:
        if offset == 0:
            return self.repo.list_daily_reports(
                report_date=report_date,
                group_name=group_name,
                limit=limit,
            )
        return self.repo.list_daily_reports(
            report_date=report_date,
            group_name=group_name,
            limit=limit,
            offset=offset,
        )

    def get_report(self, report_date: date, group_name: str) -> DailyReportDetail | None:
        return self.repo.get_daily_report(report_date=report_date, group_name=group_name)

    def export_report(self, report_date: date, group_name: str, output_path: Path) -> DailyReportExportResult:
        report = self.get_report(report_date=report_date, group_name=group_name)
        if report is None:
            raise DailyReportNotFoundError(f"daily report not found: {report_date.isoformat()} {group_name}")

        export_path = _resolve_export_path(output_path, report)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.markdown_body
        export_path.write_text(payload, encoding="utf-8")
        return DailyReportExportResult(
            export_path=export_path,
            bytes_written=len(payload.encode("utf-8")),
        )


def _resolve_export_path(output_path: Path, report: DailyReportDetail) -> Path:
    if output_path.suffix.lower() == ".md":
        return output_path
    safe_group_name = _safe_filename(report.group_name)
    return output_path / report.report_date.isoformat() / f"{safe_group_name}.md"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", value).strip().strip(".")
    return cleaned or "group"
