from __future__ import annotations

import logging

import httpx
import pytest

from app.content.article_content import ContentFetchError
from app.content.werss_provider import WeRSSContentProvider
from app.domain.article_parsing import ArticleParseSource


SECRET = "fixture-secret-body"


def source(locator="safe-id"):
    return ArticleParseSource("h", "acct", "Fallback", "https://example/a", None, "Alice", "digest", locator, "werss_article_id")


def provider(handler, endpoint="http://127.0.0.1:8001"):
    return WeRSSContentProvider(endpoint=endpoint, transport=httpx.MockTransport(handler))


def test_returns_normalized_visible_text_and_metadata():
    html = b"<html><head><style>bad</style><script>bad</script></head><body><h1> Hello </h1><p>world</p><iframe>bad</iframe></body></html>"
    result = provider(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=html)).parse(source())
    assert result.body_text == "Hello world"
    assert (result.title, result.author, result.digest, result.source) == ("Fallback", "Alice", "digest", "werss")


def test_extracts_only_article_content_and_canonicalizes_digit_span_whitespace():
    html = b"<body>navigation<div class='article-content'><span>12</span> <span>34</span></div>footer</body>"
    result = provider(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=html)).parse(source())
    assert result.body_text == "12 34"


def test_article_content_selector_stops_after_void_elements_and_container_end():
    html = b"<body><div class='article-content'>safe<br><img src='x'><hr></div>footer</body>"
    result = provider(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=html)).parse(source())
    assert result.body_text == "safe"


def test_requests_verified_werss_views_article_contract():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"safe")
    provider(handler).parse(source("MP_WXS_3545051769_abc-123"))
    assert seen["path"] == "/views/article/MP_WXS_3545051769_abc-123"


@pytest.mark.parametrize("response,code", [
    (httpx.Response(200, headers={"content-type": "text/html"}, content=b"<script>x</script>"), "werss_content_empty"),
    (httpx.Response(404), "werss_not_found"),
    (httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}"), "werss_content_type_blocked"),
    (httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * (5 * 1024 * 1024 + 1)), "werss_too_large"),
])
def test_maps_guard_failures(response, code):
    with pytest.raises(ContentFetchError) as caught:
        provider(lambda request: response).parse(source())
    assert caught.value.code == code


def test_timeout_is_recoverable():
    def timeout(request):
        raise httpx.ReadTimeout("late", request=request)
    with pytest.raises(ContentFetchError) as caught:
        provider(timeout).parse(source())
    assert (caught.value.code, caught.value.recoverable) == ("werss_timeout", True)


@pytest.mark.parametrize("locator", [None, "../secret", "a/b", "%2e%2e"])
def test_rejects_missing_or_unsafe_locator_without_request(locator):
    code = "werss_locator_missing" if locator is None else "werss_endpoint_blocked"
    with pytest.raises(ContentFetchError) as caught:
        provider(lambda request: pytest.fail("must not request")).parse(source(locator))
    assert caught.value.code == code


def test_endpoint_must_be_exact_loopback_origin():
    with pytest.raises(ContentFetchError) as caught:
        provider(lambda request: pytest.fail("must not request"), "http://localhost:8001").parse(source())
    assert caught.value.code == "werss_endpoint_blocked"


def test_redirect_outside_exact_origin_is_blocked():
    with pytest.raises(ContentFetchError) as caught:
        provider(lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1:8002/article/x"})).parse(source())
    assert caught.value.code == "werss_redirect_blocked"


def test_body_never_appears_in_exception_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    response = httpx.Response(500, content=SECRET.encode())
    with pytest.raises(ContentFetchError) as caught:
        provider(lambda request: response).parse(source())
    assert caught.value.code == "werss_http_error"
    assert SECRET not in str(caught.value)
    assert SECRET not in caplog.text
