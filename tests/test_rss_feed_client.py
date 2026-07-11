from __future__ import annotations

import httpx
import pytest

from app.rss.feed_client import FeedFetchError, RssFeedClient


RSS = """<?xml version='1.0'?><rss version='2.0'><channel><item><title>今日蛋价</title><link>https://example.com/a</link><pubDate>Sat, 11 Jul 2026 10:00:00 GMT</pubDate><author>Alice</author><description>Hello</description></item></channel></rss>""".encode()
ATOM = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Atom item</title><link href='https://example.com/b'/><updated>2026-07-11T10:00:00Z</updated><author><name>Bob</name></author><summary>World</summary></entry></feed>"""


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


def test_fetch_maps_atom():
    result = make_client(lambda request: httpx.Response(200, content=ATOM)).fetch("https://feed.example/a", timeout_seconds=3, etag=None, modified=None)
    assert (result.items[0].title, result.items[0].author) == ("Atom item", "Bob")


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
    client = make_client(lambda request: httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1)))
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
        return httpx.Response(304)
    make_client(handler, resolver=lambda host: ["93.184.216.34"]).fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
    assert seen == {"url": "https://93.184.216.34/rss", "host": "feed.example"}


def test_fetch_accepts_a_public_ip_literal():
    client = make_client(lambda request: httpx.Response(304), resolver=lambda host: pytest.fail("literal must not resolve"))
    assert client.fetch("https://93.184.216.34/rss", timeout_seconds=3, etag=None, modified=None).not_modified


@pytest.mark.parametrize("answers", [[], ["93.184.216.34", "10.0.0.1"], ["100.64.0.1"]])
def test_fetch_fails_closed_for_unsafe_dns_answers(answers):
    client = make_client(lambda request: httpx.Response(304), resolver=lambda host: answers)
    with pytest.raises(FeedFetchError, match="feed_redirect_blocked"):
        client.fetch("https://feed.example/rss", timeout_seconds=3, etag=None, modified=None)
