from __future__ import annotations

import httpx
import pytest
import gzip
from urllib.parse import urlsplit

from app.rss.feed_client import FeedFetchError, RssFeedClient


RSS = """<?xml version='1.0'?><rss version='2.0'><channel><item><title>今日蛋价</title><link>https://example.com/a</link><pubDate>Sat, 11 Jul 2026 10:00:00 GMT</pubDate><author>Alice</author><description>Hello</description></item></channel></rss>""".encode()
ATOM = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Atom item</title><link href='https://example.com/b'/><updated>2026-07-11T10:00:00Z</updated><author><name>Bob</name></author><summary>World</summary></entry></feed>"""
RECOVERABLE_BOZO_RSS = b'''<?xml version="1.0" encoding="ascii"?><rss version="2.0"><channel><item><title>\xe4\xbb\x8a</title><link>https://example.com/a</link></item></channel></rss>'''


def make_client(handler, resolver=lambda _host: ["93.184.216.34"], allowed_endpoint=None):
    return RssFeedClient(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        allowed_endpoint=allowed_endpoint,
    )


def test_fetch_sends_cache_headers_and_maps_rss():
    seen = {}
    def handler(request):
        seen["request"] = request
        return httpx.Response(200, headers={"ETag": '"v2"'}, content=RSS)
    result = make_client(handler).fetch("https://feed.example/rss", timeout_seconds=30, etag='"v1"', modified=None)
    assert seen["request"].headers["If-None-Match"] == '"v1"'
    assert result.items[0].title == "\u4eca\u65e5\u86cb\u4ef7"
    assert result.etag == '"v2"'


def test_fetch_returns_not_modified():
    client = make_client(lambda request: httpx.Response(304))
    assert client.fetch("https://feed.example/rss", timeout_seconds=30, etag='"v1"', modified=None).not_modified


def test_fetch_sends_if_modified_since():
    seen = {}
    def handler(request):
        seen["value"] = request.headers["If-Modified-Since"]
        return httpx.Response(304)
    make_client(handler).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified="Sat, 11 Jul 2026 10:00:00 GMT")
    assert seen["value"] == "Sat, 11 Jul 2026 10:00:00 GMT"


def test_fetch_maps_atom():
    result = make_client(lambda request: httpx.Response(200, content=ATOM)).fetch("https://feed.example/a", timeout_seconds=3, etag=None, modified=None)
    assert (result.items[0].title, result.items[0].author) == ("Atom item", "Bob")


def test_item_extracts_only_stable_id_from_werss_article_view_path():
    item = RssFeedClient._item({"title": "x", "link": "https://mp.weixin.qq.com/s/a", "article_view": "/views/article/Abc_123-x"})
    assert item.content_locator == "Abc_123-x"
    assert item.content_locator_type == "werss_article_id"


@pytest.mark.parametrize("value", ["/views/article/", "/views/article/a/b", "/views/article/../secret", "/views/article/" + "a" * 201])
def test_item_rejects_unsafe_werss_article_view_path(value):
    item = RssFeedClient._item({"title": "x", "link": "https://mp.weixin.qq.com/s/a", "article_view": value})
    assert item.content_locator is None
    assert item.content_locator_type is None


def test_fetch_accepts_recognized_feed_with_recoverable_encoding_bozo():
    result = make_client(lambda request: httpx.Response(200, content=RECOVERABLE_BOZO_RSS)).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
    assert result.items[0].title == "今"


@pytest.mark.parametrize("content", [b"not xml", b"<rss><broken>"])
def test_fetch_rejects_invalid_format(content):
    client = make_client(lambda request: httpx.Response(200, content=content))
    with pytest.raises(FeedFetchError, match="feed_invalid_format"):
        client.fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)


def test_fetch_maps_timeout():
    def handler(request): raise httpx.ReadTimeout("late", request=request)
    with pytest.raises(FeedFetchError, match="feed_timeout"):
        make_client(handler).fetch("https://feed.example/rss", timeout_seconds=1, etag=None, modified=None)


def test_fetch_rejects_decompressed_body_over_five_mib():
    compressed = gzip.compress(b"x" * (5 * 1024 * 1024 + 1))
    client = make_client(lambda request: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=compressed))
    with pytest.raises(FeedFetchError, match="feed_too_large"):
        client.fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)


def test_fetch_uses_configured_response_limit():
    client = RssFeedClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=RSS)),
        resolver=lambda _host: ["93.184.216.34"],
        max_response_bytes=len(RSS) - 1,
    )
    with pytest.raises(FeedFetchError, match="feed_too_large"):
        client.fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)


def test_redirect_is_validated_without_initial_endpoint_exception():
    def handler(request): return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
    client = make_client(handler, resolver=lambda host: ["127.0.0.1"], allowed_endpoint=("werss.local", 8001))
    with pytest.raises(FeedFetchError, match="feed_redirect_blocked"):
        client.fetch("http://werss.local:8001/feed", timeout_seconds=3, etag=None, modified=None)


def test_transport_is_pinned_to_validated_dns_answer():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url); seen["host"] = request.headers["host"]
        seen["sni_hostname"] = request.extensions["sni_hostname"]
        return httpx.Response(304)
    make_client(handler, resolver=lambda host: ["93.184.216.34"]).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
    assert seen == {"url": "https://93.184.216.34/rss", "host": "feed.example", "sni_hostname": b"feed.example"}


def test_trusted_hostname_is_resolved_once_and_pinned_even_when_private():
    calls = []
    seen = {}
    def resolver(host):
        calls.append(host)
        return ["127.0.0.1"]
    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(304)
    make_client(handler, resolver=resolver, allowed_endpoint=("werss.local", 8001)).fetch("http://werss.local:8001/feed", timeout_seconds=3, etag=None, modified=None)
    assert calls == ["werss.local"]
    assert seen["url"] == "http://127.0.0.1:8001/feed"


@pytest.mark.parametrize(
    ("url", "expected"),
    [("http://feed.example:443/rss", "feed.example:443"), ("https://feed.example:80/rss", "feed.example:80")],
)
def test_host_header_keeps_non_default_port(url, expected):
    seen = {}
    def handler(request):
        seen["host"] = request.headers["host"]
        return httpx.Response(304)
    make_client(handler, allowed_endpoint=("feed.example", int(urlsplit(url).port))).fetch(url, timeout_seconds=3, etag=None, modified=None)
    assert seen["host"] == expected


def test_cross_origin_redirect_strips_conditional_headers():
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "https://other.example/feed"})
        return httpx.Response(304)
    make_client(handler).fetch("https://feed.example/rss", timeout_seconds=3, etag='"v1"', modified="yesterday")
    assert "If-None-Match" not in requests[1].headers
    assert "If-Modified-Since" not in requests[1].headers


def test_same_origin_redirect_preserves_conditional_headers():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "/next"}) if len(requests) == 1 else httpx.Response(304)
    make_client(handler).fetch("https://feed.example/rss", timeout_seconds=3, etag='"v1"', modified=None)
    assert requests[1].headers["If-None-Match"] == '"v1"'


@pytest.mark.parametrize("content", [b"<rss version='2.0'><channel></channel></rss>", b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>"])
def test_valid_empty_feed_succeeds(content):
    result = make_client(lambda request: httpx.Response(200, content=content)).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
    assert result.items == ()


def test_allows_at_most_three_redirects():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(302, headers={"Location": f"/hop-{count}"})
    with pytest.raises(FeedFetchError, match="feed_redirect_blocked"):
        make_client(handler).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
    assert count == 4


@pytest.mark.parametrize("status,headers", [(302, {}), (500, {})])
def test_redirect_without_location_and_http_failure_are_mapped(status, headers):
    code = "feed_redirect_blocked" if status == 302 else "feed_http_error"
    with pytest.raises(FeedFetchError, match=code):
        make_client(lambda request: httpx.Response(status, headers=headers)).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)


def test_fetch_accepts_a_public_ip_literal():
    client = make_client(lambda request: httpx.Response(304), resolver=lambda host: pytest.fail("literal must not resolve"))
    assert client.fetch("https://93.184.216.34/rss", timeout_seconds=3, etag=None, modified=None).not_modified


@pytest.mark.parametrize("answers", [[], ["93.184.216.34", "10.0.0.1"], ["100.64.0.1"]])
def test_fetch_fails_closed_for_unsafe_dns_answers(answers):
    client = make_client(lambda request: httpx.Response(304), resolver=lambda host: answers)
    with pytest.raises(FeedFetchError, match="feed_redirect_blocked"):
        client.fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
