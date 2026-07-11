from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from ipaddress import ip_address
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx

from app.rss.models import FeedFetchResult, FeedItem
from app.rss.url_safety import FeedUrlBlocked, resolve_host, validate_feed_url

MAX_BODY_BYTES = 5 * 1024 * 1024


class FeedFetchError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RssFeedClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str], Sequence[str]] = resolve_host,
        allowed_endpoint: tuple[str, int] | None = None,
    ) -> None:
        self._transport = transport
        self._resolver = resolver
        self._allowed_endpoint = allowed_endpoint

    def fetch(self, url: str, *, timeout_seconds: int, etag: str | None, modified: str | None) -> FeedFetchResult:
        started = time.monotonic()
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9"}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        current, addresses = self._validate(url, initial=True)
        try:
            with httpx.Client(follow_redirects=False, timeout=timeout_seconds, transport=self._transport) as client:
                for redirects in range(4):
                    request_url, request_headers, extensions = self._pin(current, headers, addresses)
                    with client.stream("GET", request_url, headers=request_headers, extensions=extensions) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirects == 3 or not response.headers.get("location"):
                                raise FeedFetchError("feed_redirect_blocked")
                            current, addresses = self._validate(urljoin(current, response.headers["location"]), initial=False)
                            continue
                        if response.status_code == 304:
                            return self._result(response, (), True, started)
                        if response.status_code < 200 or response.status_code >= 300:
                            raise FeedFetchError("feed_http_error")
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BODY_BYTES:
                                raise FeedFetchError("feed_too_large")
                        parsed = feedparser.parse(bytes(body))
                        if parsed.bozo or not parsed.entries:
                            raise FeedFetchError("feed_invalid_format")
                        items = tuple(self._item(entry) for entry in parsed.entries)
                        return self._result(response, items, False, started)
        except FeedFetchError:
            raise
        except httpx.TimeoutException:
            raise FeedFetchError("feed_timeout") from None
        except httpx.HTTPError:
            raise FeedFetchError("feed_http_error") from None
        raise FeedFetchError("feed_redirect_blocked")

    def _validate(self, url: str, *, initial: bool) -> tuple[str, list[str]]:
        answers: list[str] = []
        def resolving(host: str) -> Sequence[str]:
            resolved = list(self._resolver(host))
            answers.extend(resolved)
            return resolved
        try:
            normalized = validate_feed_url(url, resolver=resolving, allowed_endpoint=self._allowed_endpoint if initial else None)
            parsed = urlsplit(normalized)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            exception = initial and self._allowed_endpoint and (parsed.hostname or "").lower() == self._allowed_endpoint[0].lower() and port == self._allowed_endpoint[1]
            host = parsed.hostname or ""
            try:
                ip_address(host)
                literal = True
            except ValueError:
                literal = False
            return normalized, ([host] if exception or literal else answers)
        except FeedUrlBlocked:
            raise FeedFetchError("feed_redirect_blocked") from None

    def _pin(self, url: str, headers: dict[str, str], addresses: list[str]):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not addresses:
            raise FeedFetchError("feed_redirect_blocked")
        address = addresses[0]
        netloc = f"[{address}]" if ":" in address else address
        if port != (443 if parsed.scheme == "https" else 80): netloc += f":{port}"
        pinned = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
        outgoing = dict(headers)
        outgoing["Host"] = host if port in {80, 443} else f"{host}:{port}"
        extensions = {"sni_hostname": host.encode()} if parsed.scheme == "https" else {}
        return pinned, outgoing, extensions

    @staticmethod
    def _item(entry) -> FeedItem:
        link = entry.get("link", "")
        return FeedItem(entry.get("title", ""), link, entry.get("published"), entry.get("updated"), entry.get("author"), entry.get("summary") or entry.get("description"))

    @staticmethod
    def _result(response, items, not_modified, started):
        return FeedFetchResult(response.status_code, response.headers.get("etag"), response.headers.get("last-modified"), tuple(items), not_modified, int((time.monotonic() - started) * 1000))
