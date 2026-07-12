from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import quote, urljoin, urlsplit

import httpx

from app.content.article_content import ArticleContent, ContentFetchError, normalize_article_text
from app.domain.article_parsing import ArticleParseSource


_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_ORIGIN = ("http", "127.0.0.1", 8001)
_LOCATOR = re.compile(r"^[A-Za-z0-9_-]+$")
_VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []
        self.article_parts: list[str] = []
        self.article_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_map = dict(attrs)
        if self.article_depth and tag.lower() not in _VOID_ELEMENTS:
            self.article_depth += 1
        elif "article-content" in (attrs_map.get("class") or "").split():
            self.article_depth = 1
        if tag.lower() in {"script", "style", "iframe"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "iframe"} and self.hidden_depth:
            self.hidden_depth -= 1
        if self.article_depth:
            self.article_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)
            if self.article_depth:
                self.article_parts.append(data)


class WeRSSContentProvider:
    def __init__(self, endpoint: str = "http://127.0.0.1:8001", transport: httpx.BaseTransport | None = None, timeout_seconds: float = 10, max_response_bytes: int = _MAX_BYTES) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._transport = transport
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def parse(self, source: ArticleParseSource) -> ArticleContent:
        locator = source.content_locator
        if not locator:
            raise ContentFetchError("werss_locator_missing", True)
        if not _LOCATOR.fullmatch(locator) or not self._allowed(self._endpoint):
            raise ContentFetchError("werss_endpoint_blocked", False)
        url = f"{self._endpoint}/article/{quote(locator, safe='')}"
        body = self._fetch(url)
        parser = _VisibleTextParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        text = normalize_article_text(" ".join(parser.article_parts or parser.parts))
        if not text:
            raise ContentFetchError("werss_content_empty", True)
        return ArticleContent(text, source.title, source.publish_time, source.author, source.digest, "werss")

    def _fetch(self, url: str) -> bytes:
        try:
            with httpx.Client(follow_redirects=False, timeout=self._timeout, transport=self._transport) as client:
                for hop in range(4):
                    if not self._allowed(url):
                        raise ContentFetchError("werss_redirect_blocked", False)
                    with client.stream("GET", url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if hop == 3 or not response.headers.get("location"):
                                raise ContentFetchError("werss_redirect_blocked", False)
                            url = urljoin(url, response.headers["location"])
                            continue
                        if response.status_code == 404:
                            raise ContentFetchError("werss_not_found", True)
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ContentFetchError("werss_http_error", True)
                        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
                            raise ContentFetchError("werss_content_type_blocked", False)
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > self._max_response_bytes:
                                raise ContentFetchError("werss_too_large", False)
                            chunks.append(chunk)
                        return b"".join(chunks)
        except ContentFetchError:
            raise
        except httpx.TimeoutException:
            raise ContentFetchError("werss_timeout", True) from None
        except httpx.HTTPError:
            raise ContentFetchError("werss_http_error", True) from None
        raise ContentFetchError("werss_redirect_blocked", False)

    @staticmethod
    def _allowed(url: str) -> bool:
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError:
            return False
        return (parsed.scheme, parsed.hostname, port) == _ALLOWED_ORIGIN and parsed.username is None and parsed.password is None
