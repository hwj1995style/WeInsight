from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, MutableMapping, Protocol

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


class ShadowArticleContentProvider:
    def __init__(
        self,
        web: ArticleContentProvider,
        werss: ArticleContentProvider,
        metrics: MutableMapping[str, int] | None = None,
    ) -> None:
        self.web, self.werss = web, werss
        self.metrics = metrics if metrics is not None else {}

    def parse(self, source: ArticleParseSource) -> ArticleContent:
        web_content = self.web.parse(source)
        try:
            werss_content = self.werss.parse(source)
        except ContentFetchError:
            self._increment("shadow_werss_failure_count")
            return web_content
        if len(web_content.body_text) != len(werss_content.body_text):
            self._increment("shadow_length_difference_count")
        if _body_hash(web_content.body_text) != _body_hash(werss_content.body_text):
            self._increment("shadow_hash_difference_count")
        return web_content

    def _increment(self, key: str) -> None:
        self.metrics[key] = self.metrics.get(key, 0) + 1


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
