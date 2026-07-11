from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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
    if item.published is None:
        raise FeedItemInvalid("published is required")
    timestamp = item.published.strip() or (item.updated or "").strip()
    if not timestamp:
        raise FeedItemInvalid("published is required")
    publish_time = _parse_publish_time(timestamp)
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
    if parsed.scheme.lower() not in {"http", "https"} or (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        raise FeedItemInvalid("article URL is not an allowed WeChat URL")
    if not (parsed.path == "/s" or parsed.path.startswith("/s/")):
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
