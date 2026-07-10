from __future__ import annotations

from datetime import date, datetime

from app.pipelines.group_daily_report_query_service import (
    DailyReportDetail,
    DailyReportSummary,
    GroupDailyReportQueryService,
)


class FakeDailyReportQueryRepo:
    def __init__(self, detail: DailyReportDetail | None = None) -> None:
        self.detail = detail
        self.list_calls: list[tuple[date, str | None, int]] = []
        self.get_calls: list[tuple[date, str]] = []

    def list_daily_reports(self, report_date: date, group_name: str | None, limit: int) -> list[DailyReportSummary]:
        self.list_calls.append((report_date, group_name, limit))
        return [
            DailyReportSummary(
                report_date=report_date,
                group_name="核心群A",
                title="核心群A 2026-07-03 群日报草稿",
                message_count=14,
                sender_count=7,
                demand_count=0,
                supply_count=1,
                contact_count=0,
                peak_hour=10,
                generate_time=datetime(2026, 7, 3, 18, 0, 0),
            )
        ]

    def get_daily_report(self, report_date: date, group_name: str) -> DailyReportDetail | None:
        self.get_calls.append((report_date, group_name))
        return self.detail


def _detail() -> DailyReportDetail:
    return DailyReportDetail(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        title="核心群A 2026-07-03 群日报草稿",
        markdown_body="# 核心群A 2026-07-03 群日报草稿\n\n## 核心指标\n- 消息数：14\n",
        message_count=14,
        sender_count=7,
        demand_count=0,
        supply_count=1,
        contact_count=0,
        peak_hour=10,
        top_keywords='[{"keyword":"深圳","count":2}]',
        report_version="v1",
        generate_time=datetime(2026, 7, 3, 18, 0, 0),
    )


def test_group_daily_report_query_service_lists_summaries() -> None:
    repo = FakeDailyReportQueryRepo()
    service = GroupDailyReportQueryService(repo=repo)

    reports = service.list_reports(report_date=date(2026, 7, 3), group_name=None, limit=20)

    assert len(reports) == 1
    assert reports[0].group_name == "核心群A"
    assert reports[0].message_count == 14
    assert repo.list_calls == [(date(2026, 7, 3), None, 20)]


def test_group_daily_report_query_service_gets_detail() -> None:
    repo = FakeDailyReportQueryRepo(detail=_detail())
    service = GroupDailyReportQueryService(repo=repo)

    report = service.get_report(report_date=date(2026, 7, 3), group_name="核心群A")

    assert report is not None
    assert report.markdown_body.startswith("# 核心群A")
    assert repo.get_calls == [(date(2026, 7, 3), "核心群A")]


def test_group_daily_report_query_service_exports_markdown_to_default_file(tmp_path) -> None:
    repo = FakeDailyReportQueryRepo(detail=_detail())
    service = GroupDailyReportQueryService(repo=repo)

    result = service.export_report(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        output_path=tmp_path,
    )

    assert result.export_path == tmp_path / "2026-07-03" / "核心群A.md"
    assert result.export_path.read_text(encoding="utf-8").startswith("# 核心群A")
    assert result.bytes_written > 0
