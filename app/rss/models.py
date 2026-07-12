from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    published: str | None
    updated: str | None
    author: str | None
    digest: str | None
    content_locator: str | None = None
    content_locator_type: str | None = None


@dataclass(frozen=True)
class FeedFetchResult:
    status_code: int
    etag: str | None
    modified: str | None
    items: tuple[FeedItem, ...]
    not_modified: bool
    elapsed_ms: int
