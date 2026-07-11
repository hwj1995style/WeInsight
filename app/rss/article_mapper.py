from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from app.domain.hashes import article_hash
from app.rss.models import FeedItem
from app.storage.article_raw_repo import RawArticleRecord


class FeedItemInvalid(ValueError):
    pass


def map_feed_item(
    *, item: FeedItem, account_name: str, batch_id: str, collect_time: datetime
) -> RawArticleRecord:
    title = _required(item.title, "title")
    link = _normalize_article_url(_required(item.link, "link"))
    publish_time = _first_valid_publish_time(item.published, item.updated)
    return RawArticleRecord(
        article_hash=article_hash(
            account_name=account_name,
            title=title,
            publish_time=publish_time,
            url=link,
        ),
        account_name=account_name,
        title=title,
        article_url=link,
        publish_time=publish_time,
        collect_time=collect_time,
        author=item.author,
        digest=item.digest,
        collect_batch_id=batch_id,
    )


def _required(value: str | None, field: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise FeedItemInvalid(f"{field} is required")
    return normalized


def _normalize_article_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        explicit_port = parsed.port is not None
    except ValueError as exc:
        raise FeedItemInvalid("article URL has an invalid port") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or (parsed.hostname or "").lower() != "mp.weixin.qq.com"
        or parsed.username is not None
        or parsed.password is not None
        or explicit_port
    ):
        raise FeedItemInvalid("article URL is not an allowed WeChat URL")
    path_segments = [unquote(segment) for segment in parsed.path.split("/")]
    if any(segment in {".", ".."} for segment in path_segments):
        raise FeedItemInvalid("article URL contains a dot segment")
    if not (
        parsed.path == "/s"
        or (parsed.path.startswith("/s/") and len(path_segments) == 3 and bool(path_segments[2]))
    ):
        raise FeedItemInvalid("URL is not a WeChat article")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit(("https", "mp.weixin.qq.com", parsed.path, query, ""))


def _parse_publish_time(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FeedItemInvalid("published is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _first_valid_publish_time(published: str | None, updated: str | None) -> datetime:
    for candidate in (published, updated):
        if not candidate or not candidate.strip():
            continue
        try:
            return _parse_publish_time(candidate.strip())
        except FeedItemInvalid:
            continue
    raise FeedItemInvalid("published and updated are absent or invalid")
