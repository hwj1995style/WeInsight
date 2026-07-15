from __future__ import annotations

from app.content.article_content import ArticleContent, ArticleContentProvider, ContentFetchError
from app.domain.article_parsing import ArticleParseSource


class FallbackArticleContentProvider:
    def __init__(self, primary: ArticleContentProvider, fallback: ArticleContentProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def parse(self, source: ArticleParseSource) -> ArticleContent:
        try:
            return self.primary.parse(source)
        except ContentFetchError as exc:
            if not exc.recoverable:
                raise
            return self.fallback.parse(source)
