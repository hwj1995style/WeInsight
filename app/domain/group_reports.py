from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DailyReportSummary:
    report_date: date
    group_name: str
    title: str
    message_count: int
    sender_count: int
    demand_count: int
    supply_count: int
    contact_count: int
    peak_hour: int | None
    generate_time: datetime


@dataclass(frozen=True)
class DailyReportDetail:
    report_date: date
    group_name: str
    title: str
    markdown_body: str
    message_count: int
    sender_count: int
    demand_count: int
    supply_count: int
    contact_count: int
    peak_hour: int | None
    top_keywords: str
    report_version: str
    generate_time: datetime
