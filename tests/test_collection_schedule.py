from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo
from time import perf_counter
from zoneinfo import ZoneInfo

import pytest

from app.domain.collection_jobs import JobStatus, PipelineType, RunStatus, ScheduleSpec
from app.services.collection_schedule import (
    coalesced_scheduled_at,
    next_run_at,
    schedules_overlap,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class SpoofedShanghaiTimezone(tzinfo):
    key = "Asia/Shanghai"

    def utcoffset(self, value: datetime | None) -> timedelta:
        return timedelta(hours=-7)

    def dst(self, value: datetime | None) -> timedelta:
        return timedelta(0)


def dt(value: str, *, tz: ZoneInfo = SHANGHAI) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=tz)


def make_spec(
    *,
    effective_start: datetime | None = None,
    effective_end: datetime | None = None,
    window_start: time = time(9),
    window_end: time = time(18),
    interval_seconds: int = 600,
    timezone_name: str = "Asia/Shanghai",
) -> ScheduleSpec:
    return ScheduleSpec(
        effective_start_at=effective_start or dt("2026-07-10 00:00"),
        effective_end_at=effective_end or dt("2026-07-13 00:00"),
        daily_window_start=window_start,
        daily_window_end=window_end,
        interval_seconds=interval_seconds,
        timezone=timezone_name,
    )


def test_domain_enums_match_persisted_values() -> None:
    assert {item.value for item in PipelineType} == {"group", "article"}
    assert {item.value for item in JobStatus} == {
        "scheduled",
        "active",
        "stop_requested",
        "stopped",
        "completed",
        "deleted",
    }
    assert {item.value for item in RunStatus} == {
        "queued",
        "running",
        "success",
        "partial_success",
        "failed",
        "cancelled",
        "aborted",
    }


@pytest.mark.parametrize("field", ["effective_start", "effective_end"])
def test_schedule_rejects_naive_effective_datetime(field: str) -> None:
    values = {
        "effective_start": dt("2026-07-10 00:00"),
        "effective_end": dt("2026-07-13 00:00"),
    }
    values[field] = values[field].replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        make_spec(**values)


@pytest.mark.parametrize("bad_value", ["2026-07-10", object(), True])
@pytest.mark.parametrize("field", ["effective_start", "effective_end"])
def test_schedule_rejects_non_datetime_effective_value(
    field: str,
    bad_value: object,
) -> None:
    values: dict[str, object] = {
        "effective_start": dt("2026-07-10 00:00"),
        "effective_end": dt("2026-07-13 00:00"),
    }
    values[field] = bad_value

    with pytest.raises(TypeError, match=f"{field}_at must be a datetime"):
        make_spec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["effective_start", "effective_end"])
def test_schedule_rejects_tzinfo_that_spoofs_shanghai_key(field: str) -> None:
    values = {
        "effective_start": dt("2026-07-10 00:00"),
        "effective_end": dt("2026-07-13 00:00"),
    }
    values[field] = datetime(2026, 7, 10, tzinfo=SpoofedShanghaiTimezone())
    if field == "effective_end":
        values[field] = datetime(2026, 7, 14, tzinfo=SpoofedShanghaiTimezone())

    with pytest.raises(ValueError, match="ZoneInfo"):
        make_spec(**values)


@pytest.mark.parametrize("timezone_name", ["UTC", "Europe/London", "PRC"])
def test_schedule_rejects_non_canonical_application_timezone(timezone_name: str) -> None:
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        make_spec(timezone_name=timezone_name)


def test_schedule_rejects_unknown_iana_timezone() -> None:
    with pytest.raises(ValueError, match="IANA"):
        make_spec(timezone_name="Mars/Olympus")


@pytest.mark.parametrize(
    "bad_datetime",
    [
        datetime(2026, 7, 10, tzinfo=timezone.utc),
        datetime(2026, 7, 10, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_schedule_rejects_effective_datetime_outside_canonical_zone(
    bad_datetime: datetime,
) -> None:
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        make_spec(effective_start=bad_datetime)


@pytest.mark.parametrize("field", ["window_start", "window_end"])
def test_schedule_rejects_time_with_tzinfo(field: str) -> None:
    values = {"window_start": time(9), "window_end": time(18)}
    values[field] = values[field].replace(tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="must not include tzinfo"):
        make_spec(**values)


@pytest.mark.parametrize("bad_value", ["09:00", object(), True])
@pytest.mark.parametrize("field", ["window_start", "window_end"])
def test_schedule_rejects_non_time_daily_window_value(
    field: str,
    bad_value: object,
) -> None:
    values: dict[str, object] = {"window_start": time(9), "window_end": time(18)}
    values[field] = bad_value

    with pytest.raises(TypeError, match=f"daily_{field} must be a time"):
        make_spec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-07-10 10:00", "2026-07-10 10:00"),
        ("2026-07-10 10:01", "2026-07-10 10:00"),
    ],
)
def test_schedule_requires_non_empty_effective_interval(start: str, end: str) -> None:
    with pytest.raises(ValueError, match="before"):
        make_spec(effective_start=dt(start), effective_end=dt(end))


@pytest.mark.parametrize("interval", [0, -1, True, False, 1.5])
def test_schedule_requires_positive_non_boolean_integer_interval(
    interval: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        make_spec(interval_seconds=interval)  # type: ignore[arg-type]


def test_next_run_inside_same_day_window() -> None:
    spec = make_spec(
        effective_start=dt("2026-07-10 09:00"),
        effective_end=dt("2026-07-12 18:00"),
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 09:01"),
        anchor=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 09:10")


def test_next_run_is_strictly_after_exact_grid_point() -> None:
    spec = make_spec()

    assert next_run_at(
        spec,
        after=dt("2026-07-10 09:10"),
        anchor=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 09:20")


def test_next_run_treats_daily_end_as_exclusive() -> None:
    spec = make_spec(interval_seconds=3600)

    assert next_run_at(
        spec,
        after=dt("2026-07-10 17:00"),
        anchor=dt("2026-07-10 09:00"),
    ) == dt("2026-07-11 09:00")


def test_next_run_includes_daily_start() -> None:
    spec = make_spec(interval_seconds=3600)

    assert next_run_at(
        spec,
        after=dt("2026-07-10 08:59:59"),
        anchor=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 09:00")


def test_cross_midnight_window_moves_to_evening_start() -> None:
    spec = make_spec(
        window_start=time(22),
        window_end=time(6),
        interval_seconds=3600,
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 12:00"),
        anchor=dt("2026-07-10 00:00"),
    ) == dt("2026-07-10 22:00")


def test_cross_midnight_window_includes_early_morning_segment() -> None:
    spec = make_spec(
        window_start=time(22),
        window_end=time(6),
        interval_seconds=3600,
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 04:00"),
        anchor=dt("2026-07-10 00:00"),
    ) == dt("2026-07-10 05:00")


def test_equal_daily_window_bounds_mean_twenty_four_hours() -> None:
    spec = make_spec(
        window_start=time(9),
        window_end=time(9),
        interval_seconds=3600,
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 18:30"),
        anchor=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 19:00")


def test_effective_start_is_inclusive_when_after_is_earlier() -> None:
    spec = make_spec(
        effective_start=dt("2026-07-10 09:00"),
        effective_end=dt("2026-07-10 12:00"),
        interval_seconds=3600,
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 08:00"),
        anchor=dt("2026-07-09 09:00"),
    ) == dt("2026-07-10 09:00")


def test_anchor_after_effective_start_defines_a_bidirectional_grid() -> None:
    spec = make_spec(
        effective_start=dt("2026-07-10 09:00"),
        effective_end=dt("2026-07-10 18:00"),
        interval_seconds=3600,
    )

    assert next_run_at(
        spec,
        after=dt("2026-07-10 08:00"),
        anchor=dt("2026-07-10 12:00"),
    ) == dt("2026-07-10 09:00")


def test_effective_end_is_exclusive() -> None:
    spec = make_spec(effective_end=dt("2026-07-10 18:00"))

    assert (
        next_run_at(
            spec,
            after=dt("2026-07-10 17:59:59"),
            anchor=dt("2026-07-10 09:00"),
        )
        is None
    )


def test_next_run_crosses_leap_day_and_month_end_without_drift() -> None:
    spec = make_spec(
        effective_start=dt("2028-02-28 00:00"),
        effective_end=dt("2028-03-02 00:00"),
        window_start=time(23, 50),
        window_end=time(0, 10),
        interval_seconds=86_400,
    )

    assert next_run_at(
        spec,
        after=dt("2028-02-29 00:10"),
        anchor=dt("2028-02-28 23:50"),
    ) == dt("2028-02-29 23:50")


def test_next_run_handles_interval_larger_than_effective_lifetime() -> None:
    spec = make_spec(
        effective_start=dt("2026-07-10 00:00"),
        effective_end=dt("2026-07-11 00:00"),
        window_start=time(0),
        window_end=time(0),
        interval_seconds=10**12,
    )

    assert (
        next_run_at(
            spec,
            after=dt("2026-07-10 00:00"),
            anchor=dt("2000-01-01 00:00"),
        )
        is None
    )


def test_next_run_search_is_bounded_for_thousands_of_years() -> None:
    spec = make_spec(
        effective_start=dt("1900-01-01 00:00"),
        effective_end=dt("9000-01-01 00:00"),
        window_start=time(12, 34, 56),
        window_end=time(12, 34, 57),
        interval_seconds=86_401,
    )

    started = perf_counter()
    result = next_run_at(
        spec,
        after=dt("1900-01-01 00:00"),
        anchor=dt("1900-01-01 00:00"),
    )

    assert result is not None
    assert result.timetz().replace(tzinfo=None) == time(12, 34, 56)
    assert perf_counter() - started < 1.0


@pytest.mark.parametrize("argument", ["after", "anchor"])
def test_next_run_rejects_naive_arguments(argument: str) -> None:
    spec = make_spec()
    values = {
        "after": dt("2026-07-10 09:00"),
        "anchor": dt("2026-07-10 09:00"),
    }
    values[argument] = values[argument].replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        next_run_at(spec, **values)


@pytest.mark.parametrize("argument", ["after", "anchor"])
def test_next_run_rejects_non_datetime_arguments(argument: str) -> None:
    values: dict[str, object] = {
        "after": dt("2026-07-10 09:00"),
        "anchor": dt("2026-07-10 09:00"),
    }
    values[argument] = "2026-07-10 09:00"

    with pytest.raises(TypeError, match=f"{argument} must be a datetime"):
        next_run_at(spec=make_spec(), **values)  # type: ignore[arg-type]


@pytest.mark.parametrize("argument", ["after", "anchor"])
def test_next_run_rejects_spoofed_shanghai_tzinfo(argument: str) -> None:
    values = {
        "after": dt("2026-07-10 09:00"),
        "anchor": dt("2026-07-10 09:00"),
    }
    values[argument] = datetime(2026, 7, 10, 9, tzinfo=SpoofedShanghaiTimezone())

    with pytest.raises(ValueError, match=f"{argument} must use .*ZoneInfo"):
        next_run_at(spec=make_spec(), **values)


def test_next_run_rejects_argument_in_another_zone() -> None:
    spec = make_spec()

    with pytest.raises(ValueError, match="Asia/Shanghai"):
        next_run_at(
            spec,
            after=datetime(2026, 7, 10, tzinfo=timezone.utc),
            anchor=dt("2026-07-10 09:00"),
        )


def test_next_run_result_is_timezone_aware_zoneinfo() -> None:
    result = next_run_at(
        make_spec(),
        after=dt("2026-07-10 09:01"),
        anchor=dt("2026-07-10 09:00"),
    )

    assert result is not None
    assert result.tzinfo is SHANGHAI
    assert result.utcoffset() == timedelta(hours=8)


def test_coalesce_returns_latest_due_grid_point() -> None:
    spec = make_spec()

    assert coalesced_scheduled_at(
        spec,
        now=dt("2026-07-10 09:37"),
        previous_next_run=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 09:30")


def test_coalesce_includes_grid_point_equal_to_now() -> None:
    spec = make_spec()

    assert coalesced_scheduled_at(
        spec,
        now=dt("2026-07-10 09:30"),
        previous_next_run=dt("2026-07-10 09:00"),
    ) == dt("2026-07-10 09:30")


def test_coalesce_returns_none_before_next_run() -> None:
    assert (
        coalesced_scheduled_at(
            make_spec(),
            now=dt("2026-07-10 09:00"),
            previous_next_run=dt("2026-07-10 09:10"),
        )
        is None
    )


def test_coalesce_returns_none_when_schedule_is_expired() -> None:
    spec = make_spec(effective_end=dt("2026-07-10 18:00"))

    assert (
        coalesced_scheduled_at(
            spec,
            now=dt("2026-07-10 18:00"),
            previous_next_run=dt("2026-07-10 17:50"),
        )
        is None
    )


def test_coalesce_returns_none_outside_current_daily_window() -> None:
    assert (
        coalesced_scheduled_at(
            make_spec(),
            now=dt("2026-07-10 19:00"),
            previous_next_run=dt("2026-07-10 17:50"),
        )
        is None
    )


def test_coalesce_rejects_invalid_previous_next_run() -> None:
    spec = make_spec()

    assert (
        coalesced_scheduled_at(
            spec,
            now=dt("2026-07-11 09:30"),
            previous_next_run=dt("2026-07-10 18:00"),
        )
        is None
    )


def test_coalesce_large_gap_is_bounded_and_does_not_replay_each_period() -> None:
    spec = make_spec(
        effective_start=dt("1900-01-01 00:00"),
        effective_end=dt("9000-01-01 00:00"),
        window_start=time(0),
        window_end=time(0),
        interval_seconds=30,
    )

    started = perf_counter()
    result = coalesced_scheduled_at(
        spec,
        now=dt("8999-12-31 23:59:59"),
        previous_next_run=dt("1900-01-01 00:00"),
    )

    assert result == dt("8999-12-31 23:59:30")
    assert perf_counter() - started < 0.2


@pytest.mark.parametrize("argument", ["now", "previous_next_run"])
def test_coalesce_rejects_naive_arguments(argument: str) -> None:
    values = {
        "now": dt("2026-07-10 09:30"),
        "previous_next_run": dt("2026-07-10 09:00"),
    }
    values[argument] = values[argument].replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        coalesced_scheduled_at(make_spec(), **values)


@pytest.mark.parametrize("argument", ["now", "previous_next_run"])
def test_coalesce_rejects_non_datetime_arguments(argument: str) -> None:
    values: dict[str, object] = {
        "now": dt("2026-07-10 09:30"),
        "previous_next_run": dt("2026-07-10 09:00"),
    }
    values[argument] = object()

    with pytest.raises(TypeError, match=f"{argument} must be a datetime"):
        coalesced_scheduled_at(make_spec(), **values)  # type: ignore[arg-type]


@pytest.mark.parametrize("argument", ["now", "previous_next_run"])
def test_coalesce_rejects_spoofed_shanghai_tzinfo(argument: str) -> None:
    values = {
        "now": dt("2026-07-10 09:30"),
        "previous_next_run": dt("2026-07-10 09:00"),
    }
    values[argument] = datetime(2026, 7, 10, 9, tzinfo=SpoofedShanghaiTimezone())

    with pytest.raises(ValueError, match=f"{argument} must use .*ZoneInfo"):
        coalesced_scheduled_at(make_spec(), **values)


def test_overlapping_effective_and_daily_windows_conflict() -> None:
    morning_job = make_spec(window_start=time(8), window_end=time(12))
    overlapping_morning_job = make_spec(window_start=time(11), window_end=time(13))
    evening_job = make_spec(window_start=time(18), window_end=time(22))

    assert schedules_overlap(morning_job, overlapping_morning_job) is True
    assert schedules_overlap(morning_job, evening_job) is False


def test_adjacent_effective_intervals_do_not_overlap() -> None:
    left = make_spec(effective_end=dt("2026-07-11 00:00"))
    right = make_spec(effective_start=dt("2026-07-11 00:00"))

    assert schedules_overlap(left, right) is False


def test_adjacent_daily_windows_do_not_overlap() -> None:
    left = make_spec(window_start=time(9), window_end=time(12))
    right = make_spec(window_start=time(12), window_end=time(18))

    assert schedules_overlap(left, right) is False


def test_cross_midnight_daily_windows_overlap_in_early_morning() -> None:
    left = make_spec(window_start=time(22), window_end=time(6))
    right = make_spec(window_start=time(5), window_end=time(7))

    assert schedules_overlap(left, right) is True


def test_cross_midnight_windows_touching_at_end_do_not_overlap() -> None:
    left = make_spec(window_start=time(22), window_end=time(6))
    right = make_spec(window_start=time(6), window_end=time(7))

    assert schedules_overlap(left, right) is False


def test_full_day_window_overlaps_any_non_empty_window() -> None:
    full_day = make_spec(window_start=time(9), window_end=time(9))
    narrow = make_spec(window_start=time(9, 1), window_end=time(9, 2))

    assert schedules_overlap(full_day, narrow) is True


def test_daily_overlap_outside_partial_effective_intersection_is_not_conflict() -> None:
    left = make_spec(
        effective_start=dt("2026-07-10 17:00"),
        effective_end=dt("2026-07-10 18:00"),
        window_start=time(9),
        window_end=time(12),
    )
    right = make_spec(
        effective_start=dt("2026-07-10 17:30"),
        effective_end=dt("2026-07-10 19:00"),
        window_start=time(10),
        window_end=time(11),
    )

    assert schedules_overlap(left, right) is False


def test_daily_overlap_inside_partial_effective_intersection_is_conflict() -> None:
    left = make_spec(
        effective_start=dt("2026-07-10 10:30"),
        effective_end=dt("2026-07-10 11:30"),
        window_start=time(9),
        window_end=time(12),
    )
    right = make_spec(
        effective_start=dt("2026-07-10 11:00"),
        effective_end=dt("2026-07-10 13:00"),
        window_start=time(10),
        window_end=time(11, 15),
    )

    assert schedules_overlap(left, right) is True


def test_schedule_overlap_handles_leap_day_boundary() -> None:
    left = make_spec(
        effective_start=dt("2028-02-29 23:30"),
        effective_end=dt("2028-03-01 00:30"),
        window_start=time(23),
        window_end=time(1),
    )
    right = make_spec(
        effective_start=dt("2028-03-01 00:00"),
        effective_end=dt("2028-03-01 01:00"),
        window_start=time(0),
        window_end=time(0, 15),
    )

    assert schedules_overlap(left, right) is True


def test_schedule_overlap_is_constant_time_for_long_effective_spans() -> None:
    left = make_spec(
        effective_start=dt("1900-01-01 00:00"),
        effective_end=dt("9000-01-01 00:00"),
        window_start=time(9),
        window_end=time(10),
    )
    right = make_spec(
        effective_start=dt("1900-01-01 00:00"),
        effective_end=dt("9000-01-01 00:00"),
        window_start=time(9, 59, 59),
        window_end=time(11),
    )

    started = perf_counter()
    result = schedules_overlap(left, right)

    assert result is True
    assert perf_counter() - started < 0.05
