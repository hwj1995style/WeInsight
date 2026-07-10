from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import Enum


class ArticleStage(str, Enum):
    OPEN_ACCOUNT = "open_account"
    LIST_ARTICLES = "list_articles"
    COPY_LINKS = "copy_links"
    SAVE_LINKS = "save_links"
    RELEASE_UI = "release_ui"
    PARSE_ARTICLE_IN_BROWSER = "parse_article_in_browser"
    WRITE_ARTICLE_RAW = "write_article_raw"
    DONE = "done"


class ArticleUiDecision(str, Enum):
    RUN = "run"
    DEFER = "defer"


@dataclass(frozen=True)
class ArticleProgress:
    crawl_date: str
    account_name: str
    stage: ArticleStage
    status: str
    last_article_url: str | None = None
    retry_count: int = 0

    def mark_running(self) -> "ArticleProgress":
        return replace(self, status="running")

    def mark_interrupted(self) -> "ArticleProgress":
        return replace(self, status="interrupted", retry_count=self.retry_count + 1)


def should_defer_article_ui(
    *,
    now: datetime,
    next_core_group_due: datetime,
    min_article_ui_window_seconds: int,
) -> ArticleUiDecision:
    remaining = (next_core_group_due - now).total_seconds()
    if remaining < min_article_ui_window_seconds:
        return ArticleUiDecision.DEFER
    return ArticleUiDecision.RUN


def should_run_article_account(
    *,
    now: datetime,
    last_success_at: datetime | None,
    active_windows: tuple[str, ...],
    account_poll_interval_minutes: int,
    next_core_group_due: datetime,
    min_article_ui_window_seconds: int,
) -> ArticleUiDecision:
    if not _is_in_any_window(now.time(), active_windows):
        return ArticleUiDecision.DEFER
    if last_success_at is not None:
        elapsed = now - last_success_at
        if elapsed < timedelta(minutes=account_poll_interval_minutes):
            return ArticleUiDecision.DEFER
    return should_defer_article_ui(
        now=now,
        next_core_group_due=next_core_group_due,
        min_article_ui_window_seconds=min_article_ui_window_seconds,
    )


def is_article_from_crawl_date(publish_time: datetime | None, crawl_date: date) -> bool:
    if publish_time is None:
        return False
    return publish_time.date() == crawl_date


def _is_in_any_window(value: time, windows: tuple[str, ...]) -> bool:
    for window in windows:
        start, end = _parse_time_window(window)
        if start <= value <= end:
            return True
    return False


def _parse_time_window(window: str) -> tuple[time, time]:
    start_text, end_text = window.split("-", 1)
    return (
        datetime.strptime(start_text, "%H:%M").time(),
        datetime.strptime(end_text, "%H:%M").time(),
    )


@dataclass(frozen=True)
class ArticlePipelineState:
    pending_tasks: int
    failed_tasks: int

    def mark_failed(self) -> "ArticlePipelineState":
        return replace(self, failed_tasks=self.failed_tasks + 1)
