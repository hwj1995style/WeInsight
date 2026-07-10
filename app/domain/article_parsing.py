from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ArticleParseSource:
    article_hash: str
    account_name: str
    title: str
    article_url: str
    publish_time: datetime | None
    author: str | None
    digest: str | None


@dataclass(frozen=True)
class ParsedArticleContent:
    title: str | None
    publish_time: datetime | None
    author: str | None
    digest: str | None
    content_length: int


@dataclass(frozen=True)
class CleanArticleRecord:
    article_hash: str
    account_name: str
    title: str
    article_url: str
    publish_time: datetime | None
    author: str | None
    digest: str | None
    content_length: int
    parse_time: datetime
    parse_version: str = "v1"
