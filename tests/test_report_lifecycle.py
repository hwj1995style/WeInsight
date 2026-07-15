from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.report_lifecycle import (
    GenerationTrigger,
    ReportLifecycle,
    ReportStatus,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 30, tzinfo=ZONE)


def test_provisional_builds_frozen_manual_lifecycle() -> None:
    lifecycle = ReportLifecycle.provisional(cutoff=NOW, generated_by=" admin ")

    assert lifecycle.report_status is ReportStatus.PROVISIONAL
    assert lifecycle.data_cutoff_time == NOW
    assert lifecycle.generation_trigger is GenerationTrigger.MANUAL
    assert lifecycle.last_generated_by == "admin"
    with pytest.raises(FrozenInstanceError):
        lifecycle.last_generated_by = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("report_date", "expected_status"),
    [
        (date(2026, 7, 10), ReportStatus.PROVISIONAL),
        (date(2026, 7, 9), ReportStatus.FINAL),
    ],
)
def test_manual_for_date_uses_today_provisional_and_history_final(
    report_date: date,
    expected_status: ReportStatus,
) -> None:
    lifecycle = ReportLifecycle.manual_for_date(report_date, NOW, "admin")

    assert lifecycle.report_status is expected_status
    assert lifecycle.data_cutoff_time == NOW
    assert lifecycle.generation_trigger is GenerationTrigger.MANUAL


def test_manual_for_date_rejects_future_report_date() -> None:
    with pytest.raises(ValueError, match="future"):
        ReportLifecycle.manual_for_date(date(2026, 7, 11), NOW, "admin")


@pytest.mark.parametrize(
    "cutoff",
    [
        datetime(2026, 7, 10, 9, 30),
        datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc),
    ],
)
def test_lifecycle_rejects_cutoff_outside_shanghai_zone(cutoff: datetime) -> None:
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        ReportLifecycle.provisional(cutoff=cutoff, generated_by="admin")


@pytest.mark.parametrize(
    "generated_by",
    ["", "   ", "a" * 101, "admin\nroot", "admin\x00root"],
)
def test_lifecycle_rejects_invalid_generated_by(generated_by: str) -> None:
    with pytest.raises(ValueError, match="generated_by"):
        ReportLifecycle.provisional(cutoff=NOW, generated_by=generated_by)


@pytest.mark.parametrize(
    "trigger",
    [
        GenerationTrigger.MANUAL,
        GenerationTrigger.AUTOMATIC,
        GenerationTrigger.COMPENSATION,
        GenerationTrigger.LEGACY,
    ],
)
def test_final_accepts_every_known_generation_trigger(trigger: GenerationTrigger) -> None:
    lifecycle = ReportLifecycle.final(cutoff=NOW, trigger=trigger, generated_by="system")

    assert lifecycle.report_status is ReportStatus.FINAL
    assert lifecycle.generation_trigger is trigger


def test_lifecycle_rejects_unknown_enum_values() -> None:
    with pytest.raises(ValueError, match="report_status"):
        ReportLifecycle("final", NOW, GenerationTrigger.MANUAL, "admin")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="generation_trigger"):
        ReportLifecycle(ReportStatus.FINAL, NOW, "unknown", "admin")  # type: ignore[arg-type]
