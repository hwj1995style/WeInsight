from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import parse_qs, urlparse


WECHAT_MP_URL_PATTERN = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s\"'<>]+")


def extract_article_detail_urls(values: Iterable[str], max_articles: int) -> list[str]:
    if max_articles <= 0:
        return []

    links: list[str] = []
    seen: set[str] = set()

    for value in values:
        for raw_url in WECHAT_MP_URL_PATTERN.findall(value or ""):
            url = raw_url.rstrip(".,;)]}")
            if not _is_article_detail_url(url):
                continue
            if url in seen:
                continue
            links.append(url)
            seen.add(url)
            if len(links) >= max_articles:
                return links

    return links


def read_article_url_from_clipboard_copy(
    copy_action: Callable[[], None],
    paste: Callable[[], str],
    copy: Callable[[str], None],
) -> str | None:
    original = paste()
    try:
        copy_action()
        copied_value = paste()
        links = extract_article_detail_urls([copied_value], max_articles=1)
        return links[0] if links else None
    finally:
        copy(original)


def _is_article_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != "mp.weixin.qq.com":
        return False
    path = parsed.path.rstrip("/")
    if path.startswith("/s/") and len(path) > len("/s/"):
        return True
    if path != "/s":
        return False
    query = parse_qs(parsed.query)
    return all(key in query for key in ("__biz", "mid", "idx", "sn"))
