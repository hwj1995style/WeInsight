from __future__ import annotations

from datetime import date, datetime, timedelta

from app.pipelines.article_pipeline import (
    ArticleUiDecision,
    is_article_from_crawl_date,
    should_run_article_account,
)


DEFAULT_WINDOWS = ("07:30-19:30",)


def test_article_account_defers_outside_default_window() -> None:
    now = datetime(2026, 7, 3, 7, 29)

    decision = should_run_article_account(
        now=now,
        last_success_at=None,
        active_windows=DEFAULT_WINDOWS,
        account_poll_interval_minutes=60,
        next_core_group_due=now + timedelta(minutes=30),
        min_article_ui_window_seconds=20,
    )

    assert decision == ArticleUiDecision.DEFER


def test_article_account_runs_hourly_inside_window_when_core_group_not_due() -> None:
    now = datetime(2026, 7, 3, 8, 30)

    decision = should_run_article_account(
        now=now,
        last_success_at=datetime(2026, 7, 3, 7, 30),
        active_windows=DEFAULT_WINDOWS,
        account_poll_interval_minutes=60,
        next_core_group_due=now + timedelta(minutes=10),
        min_article_ui_window_seconds=20,
    )

    assert decision == ArticleUiDecision.RUN


def test_article_account_defers_until_hourly_interval_elapsed() -> None:
    now = datetime(2026, 7, 3, 8, 29)

    decision = should_run_article_account(
        now=now,
        last_success_at=datetime(2026, 7, 3, 7, 30),
        active_windows=DEFAULT_WINDOWS,
        account_poll_interval_minutes=60,
        next_core_group_due=now + timedelta(minutes=10),
        min_article_ui_window_seconds=20,
    )

    assert decision == ArticleUiDecision.DEFER


def test_article_account_defers_when_core_group_due_too_soon() -> None:
    now = datetime(2026, 7, 3, 8, 30)

    decision = should_run_article_account(
        now=now,
        last_success_at=datetime(2026, 7, 3, 7, 30),
        active_windows=DEFAULT_WINDOWS,
        account_poll_interval_minutes=60,
        next_core_group_due=now + timedelta(seconds=10),
        min_article_ui_window_seconds=20,
    )

    assert decision == ArticleUiDecision.DEFER


def test_article_publish_date_filter_keeps_only_crawl_date_articles() -> None:
    crawl_date = date(2026, 7, 3)

    assert is_article_from_crawl_date(datetime(2026, 7, 3, 7, 45), crawl_date) is True
    assert is_article_from_crawl_date(datetime(2026, 7, 2, 23, 59), crawl_date) is False
    assert is_article_from_crawl_date(None, crawl_date) is False
