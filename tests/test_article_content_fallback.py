from datetime import datetime

import pytest

from app.content.article_content import ArticleContent, ContentFetchError
from app.content.fallback_provider import FallbackArticleContentProvider
from app.domain.article_parsing import ArticleParseSource


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def parse(self, source):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def source():
    return ArticleParseSource("h", "a", "t", "https://example.test/a", datetime(2026, 1, 1), None, None)


@pytest.mark.parametrize("code", ["werss_locator_missing", "werss_not_found", "werss_content_empty", "werss_timeout", "werss_http_error"])
def test_recoverable_content_errors_use_web_fallback(code):
    primary = Provider(ContentFetchError(code, True))
    expected = ArticleContent("正文", "标题", None, None, None, "web")
    fallback = Provider(expected)

    assert FallbackArticleContentProvider(primary, fallback).parse(source()) == expected
    assert fallback.calls == 1


@pytest.mark.parametrize("code", ["werss_endpoint_blocked", "werss_redirect_blocked", "werss_too_large", "werss_content_type_blocked"])
def test_security_content_errors_never_use_web_fallback(code):
    primary = Provider(ContentFetchError(code, False))
    fallback = Provider(ArticleContent("secret", None, None, None, None, "web"))

    with pytest.raises(ContentFetchError) as caught:
        FallbackArticleContentProvider(primary, fallback).parse(source())

    assert caught.value.code == code
    assert fallback.calls == 0
