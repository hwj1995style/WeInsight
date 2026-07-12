from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from ipaddress import ip_address
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from feedparser.exceptions import CharacterEncodingOverride, CharacterEncodingUnknown, UndeclaredNamespace

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
        max_response_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        self._transport = transport
        self._resolver = resolver
        self._allowed_endpoint = allowed_endpoint
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        self._max_response_bytes = max_response_bytes

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
                            redirect_url = urljoin(current, response.headers["location"])
                            if self._origin(current) != self._origin(redirect_url):
                                headers.pop("If-None-Match", None)
                                headers.pop("If-Modified-Since", None)
                            current, addresses = self._validate(redirect_url, initial=False)
                            continue
                        if response.status_code == 304:
                            return self._result(response, (), True, started)
                        if response.status_code < 200 or response.status_code >= 300:
                            raise FeedFetchError("feed_http_error")
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > self._max_response_bytes:
                                raise FeedFetchError("feed_too_large")
                        parsed = feedparser.parse(bytes(body))
                        recoverable_bozo = isinstance(
                            parsed.get("bozo_exception"),
                            (CharacterEncodingOverride, CharacterEncodingUnknown, UndeclaredNamespace),
                        )
                        if not parsed.get("version") or (
                            parsed.get("bozo", False) and not recoverable_bozo
                        ):
                            raise FeedFetchError("feed_invalid_format")
                        raw_ids = self._rss_item_ids_by_link(bytes(body))
                        items = tuple(
                            self._item(dict(entry, werss_standard_article_id=raw_ids.get(entry.get("link", ""))))
                            for entry in parsed.entries
                        )
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
            if exception and not literal:
                answers = list(self._resolver(host))
                if not answers:
                    raise FeedFetchError("feed_redirect_blocked")
                for answer in answers:
                    ip_address(answer)
            return normalized, ([host] if literal else answers)
        except FeedFetchError:
            raise
        except (FeedUrlBlocked, OSError, ValueError):
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
        default_port = 443 if parsed.scheme == "https" else 80
        outgoing["Host"] = host if port == default_port else f"{host}:{port}"
        extensions = {"sni_hostname": host.encode()} if parsed.scheme == "https" else {}
        return pinned, outgoing, extensions

    @staticmethod
    def _item(entry) -> FeedItem:
        link = entry.get("link", "")
        raw_standard_id = entry.get("werss_standard_article_id") or ""
        locator = raw_standard_id if re.fullmatch(r"[A-Za-z0-9_-]{1,200}", raw_standard_id) else None
        # WeRSS' standard RSS shape exposes the internal article view as guid.
        # Accept only the exact relative route; never derive it from article links,
        # absolute URLs, fragments, or query parameters.
        for key in ("werss_standard_article_id", "article_view", "content_locator", "werss_article_view", "guid", "id"):
            match = re.fullmatch(r"/views/article/([A-Za-z0-9_-]{1,200})", entry.get(key, "") or "")
            if match:
                locator = match.group(1)
                break
        return FeedItem(
            entry.get("title", ""),
            link,
            entry.get("published"),
            entry.get("updated"),
            entry.get("author"),
            entry.get("summary") or entry.get("description"),
            locator,
            "werss_article_id" if locator else None,
        )

    @staticmethod
    def _rss_item_ids_by_link(body: bytes) -> dict[str, str]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return {}
        candidates: dict[str, list[str]] = {}
        for item in root.findall("./channel/item"):
            value = item.findtext("id") or ""
            link = item.findtext("link") or item.findtext("guid") or ""
            if link and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                candidates.setdefault(link, []).append(value)
        return {link: values[0] for link, values in candidates.items() if len(values) == 1}

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

    @staticmethod
    def _result(response, items, not_modified, started):
        return FeedFetchResult(response.status_code, response.headers.get("etag"), response.headers.get("last-modified"), tuple(items), not_modified, int((time.monotonic() - started) * 1000))
