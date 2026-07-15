from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import gcd
from zoneinfo import ZoneInfo

from app.domain.collection_jobs import (
    APPLICATION_TIMEZONE,
    ScheduleSpec,
    ensure_schedule_datetime,
)


_MICROSECONDS_PER_SECOND = 1_000_000
_MICROSECONDS_PER_DAY = 86_400 * _MICROSECONDS_PER_SECOND
_APPLICATION_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


def _timedelta_microseconds(value: timedelta) -> int:
    return (
        (value.days * 86_400 + value.seconds) * _MICROSECONDS_PER_SECOND
        + value.microseconds
    )


def _difference_microseconds(left: datetime, right: datetime) -> int:
    return _timedelta_microseconds(left - right)


def _ceil_div(numerator: int, denominator: int) -> int:
    return -((-numerator) // denominator)


def _time_microseconds(value: time) -> int:
    return (
        (value.hour * 3_600 + value.minute * 60 + value.second)
        * _MICROSECONDS_PER_SECOND
        + value.microsecond
    )


def _inside_daily_window(spec: ScheduleSpec, value: datetime) -> bool:
    candidate = _time_microseconds(value.timetz().replace(tzinfo=None))
    start = _time_microseconds(spec.daily_window_start)
    end = _time_microseconds(spec.daily_window_end)
    if start == end:
        return True
    if start < end:
        return start <= candidate < end
    return candidate >= start or candidate < end


def _inside_schedule(spec: ScheduleSpec, value: datetime) -> bool:
    return (
        spec.effective_start_at <= value < spec.effective_end_at
        and _inside_daily_window(spec, value)
    )


def _candidate_at(anchor: datetime, offset_microseconds: int) -> datetime:
    return anchor + timedelta(microseconds=offset_microseconds)


def next_run_at(
    spec: ScheduleSpec,
    *,
    after: datetime,
    anchor: datetime,
) -> datetime | None:
    """Return the first valid fixed-grid instant strictly later than ``after``.

    The grid is bi-directional around ``anchor``. Search is bounded by the number
    of distinct grid residues within one local day, not by the effective lifetime.
    Asia/Shanghai has no DST transitions, while ZoneInfo still keeps the timezone
    contract explicit on every returned datetime.
    """
    ensure_schedule_datetime(after, field_name="after")
    ensure_schedule_datetime(anchor, field_name="anchor")

    step = spec.interval_seconds * _MICROSECONDS_PER_SECOND
    first_after = (
        _difference_microseconds(after, anchor) // step
    ) + 1
    first_effective = _ceil_div(
        _difference_microseconds(spec.effective_start_at, anchor),
        step,
    )
    last_effective = (
        _ceil_div(
            _difference_microseconds(spec.effective_end_at, anchor),
            step,
        )
        - 1
    )
    first = max(first_after, first_effective)
    if first > last_effective:
        return None

    candidate_count = last_effective - first + 1
    residues_per_day = _MICROSECONDS_PER_DAY // gcd(
        step,
        _MICROSECONDS_PER_DAY,
    )
    checks = min(candidate_count, residues_per_day)
    for offset in range(checks):
        grid_index = first + offset
        candidate = _candidate_at(anchor, grid_index * step)
        if _inside_daily_window(spec, candidate):
            return candidate
    return None


def coalesced_scheduled_at(
    spec: ScheduleSpec,
    *,
    now: datetime,
    previous_next_run: datetime,
) -> datetime | None:
    """Collapse all currently eligible missed periods into their latest grid key."""
    ensure_schedule_datetime(now, field_name="now")
    ensure_schedule_datetime(
        previous_next_run,
        field_name="previous_next_run",
    )
    if previous_next_run > now:
        return None
    if not _inside_schedule(spec, previous_next_run):
        return None
    # Misfires are only started while the worker is still inside the effective
    # interval and today's permitted UI window.
    if not _inside_schedule(spec, now):
        return None

    step = spec.interval_seconds * _MICROSECONDS_PER_SECOND
    latest_index = _difference_microseconds(now, previous_next_run) // step
    residues_per_day = _MICROSECONDS_PER_DAY // gcd(
        step,
        _MICROSECONDS_PER_DAY,
    )
    checks = min(latest_index + 1, residues_per_day)
    for offset in range(checks):
        grid_index = latest_index - offset
        candidate = _candidate_at(previous_next_run, grid_index * step)
        if _inside_schedule(spec, candidate):
            return candidate
    return None


def _window_segments(spec: ScheduleSpec) -> tuple[tuple[int, int], ...]:
    start = _time_microseconds(spec.daily_window_start)
    end = _time_microseconds(spec.daily_window_end)
    if start == end:
        return ((0, _MICROSECONDS_PER_DAY),)
    if start < end:
        return ((start, end),)
    return ((0, end), (start, _MICROSECONDS_PER_DAY))


def _intersecting_window_segments(
    left: ScheduleSpec,
    right: ScheduleSpec,
) -> tuple[tuple[int, int], ...]:
    intersections: list[tuple[int, int]] = []
    for left_start, left_end in _window_segments(left):
        for right_start, right_end in _window_segments(right):
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            if start < end:
                intersections.append((start, end))
    return tuple(intersections)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_APPLICATION_ZONE)


def _segment_overlaps_effective_interval(
    day: date,
    segment: tuple[int, int],
    effective_start: datetime,
    effective_end: datetime,
) -> bool:
    midnight = _midnight(day)
    segment_start = midnight + timedelta(microseconds=segment[0])
    segment_end = midnight + timedelta(microseconds=segment[1])
    return max(segment_start, effective_start) < min(segment_end, effective_end)


def schedules_overlap(left: ScheduleSpec, right: ScheduleSpec) -> bool:
    """Return whether two recurring schedules share any actual allowed instant."""
    effective_start = max(left.effective_start_at, right.effective_start_at)
    effective_end = min(left.effective_end_at, right.effective_end_at)
    if effective_start >= effective_end:
        return False

    daily_intersections = _intersecting_window_segments(left, right)
    if not daily_intersections:
        return False

    first_day = effective_start.date()
    last_day = (effective_end - timedelta(microseconds=1)).date()
    if (last_day - first_day).days >= 2:
        return True

    days = (first_day,) if first_day == last_day else (first_day, last_day)
    return any(
        _segment_overlaps_effective_interval(
            day,
            segment,
            effective_start,
            effective_end,
        )
        for day in days
        for segment in daily_intersections
    )
