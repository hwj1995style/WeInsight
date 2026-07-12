from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.domain.article_parsing import ArticleParseSource


@dataclass(frozen=True)
class ArticleContent:
    body_text: str
    title: str | None
    publish_time: datetime | None
    author: str | None
    digest: str | None
    source: Literal["werss", "web"]


class ArticleContentProvider(Protocol):
    def parse(self, source: ArticleParseSource) -> ArticleContent: ...


class ContentFetchError(Exception):
    def __init__(self, code: str, recoverable: bool):
        self.code = code
        self.recoverable = recoverable
        super().__init__(code)
