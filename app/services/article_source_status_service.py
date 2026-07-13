from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.storage.article_source_status_repo import ArticleSourceStatusRecord
from app.storage.collection_event_repo import sanitize_output


class ArticleSourceStatusRepo(Protocol):
    def list_status_page(self, *, limit: int, offset: int) -> list[ArticleSourceStatusRecord]: ...


@dataclass(frozen=True, slots=True)
class ArticleSourceStatusRow:
    account_name: str
    werss_source_id: str | None
    upstream_status: str
    display_status: str
    last_article_time: datetime | None
    last_success_collect_time: datetime | None
    article_count: int
    pending_parse_count: int
    pending_analyze_count: int
    failed_count: int
    last_error: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ArticleSourceStatusPage:
    items: tuple[ArticleSourceStatusRow, ...]
    page: int
    page_size: int
    has_previous: bool
    has_next: bool


class ArticleSourceStatusService:
    def __init__(self, repo: ArticleSourceStatusRepo, sync_interval_minutes: int) -> None:
        self.repo = repo
        self.sync_interval_minutes = sync_interval_minutes

    def list_page(self, page: int, page_size: int, now: datetime) -> ArticleSourceStatusPage:
        self._validate_page(page, page_size)
        records = self.repo.list_status_page(limit=page_size + 1, offset=(page - 1) * page_size)
        return ArticleSourceStatusPage(
            items=tuple(self.to_status(item, now) for item in records[:page_size]),
            page=page, page_size=page_size, has_previous=page > 1,
            has_next=len(records) > page_size,
        )

    def to_status(self, record: ArticleSourceStatusRecord, now: datetime) -> ArticleSourceStatusRow:
        status = self._display_status(record, now)
        error = None if record.last_error is None else sanitize_output(record.last_error, maximum=200).strip() or None
        return ArticleSourceStatusRow(
            account_name=record.account_name, werss_source_id=record.werss_source_id,
            upstream_status=record.upstream_status, display_status=status,
            last_article_time=record.last_article_time,
            last_success_collect_time=record.last_success_collect_time,
            article_count=record.article_count, pending_parse_count=record.pending_parse_count,
            pending_analyze_count=record.pending_analyze_count, failed_count=record.failed_count,
            last_error=error, updated_at=record.updated_at,
        )

    def _display_status(self, record: ArticleSourceStatusRecord, now: datetime) -> str:
        if record.upstream_status == "excluded": return "excluded"
        if record.upstream_status == "missing": return "missing"
        if record.upstream_status == "disabled": return "disabled"
        if record.last_collect_status == "failed": return "collect_error"
        if record.upstream_status == "active" and record.last_success_collect_time is None:
            return "waiting_first_run"
        threshold = timedelta(minutes=2 * self.sync_interval_minutes)
        if record.last_success_collect_time is not None and now - record.last_success_collect_time > threshold:
            return "stale"
        return "normal"

    @staticmethod
    def _validate_page(page: int, page_size: int) -> None:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be positive")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
