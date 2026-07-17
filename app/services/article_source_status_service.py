from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.storage.article_source_status_repo import ArticleSourceStatusRecord
from app.storage.collection_event_repo import sanitize_output


class ArticleSourceStatusRepo(Protocol):
    def list_status_page(self, *, limit: int, offset: int) -> list[ArticleSourceStatusRecord]: ...
    def count_status_sources(self) -> int: ...


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
    status_updated_at: datetime | None
    source_id: int = 0
    collection_enabled: bool = False
    downstream_processing_enabled: bool = False
    downstream_processing_mutable: bool = False


@dataclass(frozen=True, slots=True)
class ArticleSourceStatusPage:
    items: tuple[ArticleSourceStatusRow, ...]
    page: int
    page_size: int
    has_previous: bool
    has_next: bool
    total_count: int = 0


class ArticleSourceStatusService:
    def __init__(self, repo: ArticleSourceStatusRepo, sync_interval_minutes: int) -> None:
        self.repo = repo
        self.sync_interval_minutes = sync_interval_minutes

    def list_page(self, page: int, page_size: int, now: datetime) -> ArticleSourceStatusPage:
        self._validate_page(page, page_size)
        records = self.repo.list_status_page(limit=page_size + 1, offset=(page - 1) * page_size)
        counter = getattr(self.repo, "count_status_sources", None)
        inferred_count = (page - 1) * page_size + min(len(records), page_size)
        if len(records) > page_size:
            inferred_count += 1
        total_count = max(counter() if callable(counter) else 0, inferred_count)
        return ArticleSourceStatusPage(
            items=tuple(self.to_status(item, now) for item in records[:page_size]),
            page=page, page_size=page_size, has_previous=page > 1,
            has_next=page * page_size < total_count, total_count=total_count,
        )

    def to_status(self, record: ArticleSourceStatusRecord, now: datetime) -> ArticleSourceStatusRow:
        status = self._display_status(record, now)
        error = None if record.last_error is None else sanitize_output(record.last_error, maximum=200).strip() or None
        return ArticleSourceStatusRow(
            source_id=record.source_id,
            account_name=record.account_name, werss_source_id=record.werss_source_id,
            collection_enabled=record.collection_enabled,
            downstream_processing_enabled=record.downstream_processing_enabled,
            downstream_processing_mutable="".join(record.account_name.split()) != "一箱蛋",
            upstream_status=record.upstream_status, display_status=status,
            last_article_time=record.last_article_time,
            last_success_collect_time=record.last_success_collect_time,
            article_count=record.article_count, pending_parse_count=record.pending_parse_count,
            pending_analyze_count=record.pending_analyze_count, failed_count=record.failed_count,
            last_error=error,
            status_updated_at=max(
                value for value in (
                    record.updated_at, record.upstream_last_seen_at,
                    record.last_success_collect_time, record.latest_collect_log_time,
                ) if value is not None
            ) if any(value is not None for value in (
                record.updated_at, record.upstream_last_seen_at,
                record.last_success_collect_time, record.latest_collect_log_time,
            )) else None,
        )

    def _display_status(self, record: ArticleSourceStatusRecord, now: datetime) -> str:
        if record.upstream_status == "excluded": return "excluded"
        if record.upstream_status == "missing": return "missing"
        if record.upstream_status == "disabled": return "disabled"
        if record.upstream_status == "unknown": return "unknown"
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
