from datetime import date, datetime, timezone
import pytest

from app.domain.article_downstream import ArticleBackfillCommand, ArticleBackfillSummary
from app.services.article_downstream_service import (
    ArticleDownstreamService,
    ArticleDownstreamSourceUnavailableError,
    ArticleDownstreamValidationError,
)


SUMMARY = ArticleBackfillSummary(1, 2, 3, 4, 5, 6, 7, 8)


class Repo:
    def __init__(self, *, mutable=True, error=None):
        self.mutable = mutable
        self.error = error
        self.calls = []

    def set_processing_enabled(self, source_id, enabled):
        self.calls.append(("set", source_id, enabled))
        if self.error:
            raise self.error
        return self.mutable

    def enqueue_backfill(self, command, now):
        self.calls.append(("backfill", command, now))
        if self.error:
            raise self.error
        return SUMMARY


def command(**changes):
    values = dict(scope="single", source_id=7, start_date=date(2026, 7, 1),
                  end_date=date(2026, 7, 14), mode="missing_only", force_confirmed=False)
    values.update(changes)
    return ArticleBackfillCommand(**values)


@pytest.mark.parametrize("source_id", [True, False, 0, -1, 1.0, "1", None])
def test_set_rejects_non_positive_integer_source_id_before_repo(source_id):
    repo = Repo()
    with pytest.raises(ArticleDownstreamValidationError, match="source_id"):
        ArticleDownstreamService(repo).set_processing_enabled(source_id, True)
    assert repo.calls == []


@pytest.mark.parametrize("enabled", [0, 1, None, "true"])
def test_set_requires_a_strict_boolean(enabled):
    repo = Repo()
    with pytest.raises(ArticleDownstreamValidationError, match="enabled"):
        ArticleDownstreamService(repo).set_processing_enabled(7, enabled)
    assert repo.calls == []


def test_set_translates_missing_outside_catalog_and_yixiangdan_to_stable_error():
    repo = Repo(mutable=False)
    with pytest.raises(ArticleDownstreamSourceUnavailableError) as raised:
        ArticleDownstreamService(repo).set_processing_enabled(7, True)
    assert str(raised.value) == "article source is unavailable for downstream processing"


def test_set_translates_repo_lookup_without_leaking_details():
    repo = Repo(error=LookupError("SELECT secret FROM config"))
    with pytest.raises(ArticleDownstreamSourceUnavailableError) as raised:
        ArticleDownstreamService(repo).set_processing_enabled(7, True)
    assert "SELECT" not in str(raised.value)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"scope": "other"}, "scope"),
        ({"scope": "single", "source_id": None}, "source_id"),
        ({"scope": "single", "source_id": True}, "source_id"),
        ({"scope": "enabled", "source_id": 7}, "source_id"),
        ({"mode": "other"}, "mode"),
        ({"force_confirmed": 1}, "force_confirmed"),
        ({"mode": "force_analyze", "force_confirmed": False}, "confirmation"),
        ({"start_date": datetime(2026, 7, 1)}, "start_date"),
        ({"end_date": "2026-07-14"}, "end_date"),
        ({"start_date": date(2026, 7, 15)}, "start_date"),
        ({"start_date": date(2026, 6, 13)}, "31"),
        ({"end_date": date(2026, 7, 15)}, "future"),
    ],
)
def test_backfill_rejects_invalid_commands_before_repo(changes, message):
    repo = Repo()
    with pytest.raises(ArticleDownstreamValidationError, match=message):
        ArticleDownstreamService(repo).backfill(command(**changes), datetime(2026, 7, 14, 12))
    assert repo.calls == []


def test_backfill_accepts_inclusive_31_day_boundary_and_only_orchestrates_repo():
    repo = Repo()
    cmd = command(start_date=date(2026, 6, 14), end_date=date(2026, 7, 14))
    now = datetime(2026, 7, 14, 12)
    assert ArticleDownstreamService(repo).backfill(cmd, now) == SUMMARY
    assert repo.calls == [("backfill", cmd, now)]


def test_force_analyze_accepts_strict_confirmation():
    repo = Repo()
    cmd = command(mode="force_analyze", force_confirmed=True)
    assert ArticleDownstreamService(repo).backfill(cmd, datetime(2026, 7, 14)) == SUMMARY


def test_backfill_translates_catalog_lookup_without_leaking_details():
    repo = Repo(error=LookupError("SQL catalog detail"))
    with pytest.raises(ArticleDownstreamSourceUnavailableError) as raised:
        ArticleDownstreamService(repo).backfill(command(), datetime(2026, 7, 14))
    assert str(raised.value) == "article source is unavailable for downstream processing"


def test_default_dates_are_today_and_previous_six_days_for_naive_now():
    assert ArticleDownstreamService.default_backfill_dates(datetime(2026, 7, 14, 1)) == (
        date(2026, 7, 8), date(2026, 7, 14))


def test_aware_now_is_converted_to_shanghai_for_defaults_and_future_check():
    now = datetime(2026, 7, 14, 16, 30, tzinfo=timezone.utc)  # Shanghai: July 15
    assert ArticleDownstreamService.default_backfill_dates(now) == (
        date(2026, 7, 9), date(2026, 7, 15))
    repo = Repo()
    assert ArticleDownstreamService(repo).backfill(
        command(end_date=date(2026, 7, 15)), now) == SUMMARY


def test_non_datetime_now_is_rejected_without_date_datetime_confusion():
    with pytest.raises(ArticleDownstreamValidationError, match="now"):
        ArticleDownstreamService.default_backfill_dates(date(2026, 7, 14))
