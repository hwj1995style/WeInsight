from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.rss.article_mapper import FeedItemInvalid, map_feed_item
from app.rss.models import FeedItem


ITEM = FeedItem(
    title=" 示例文章 ",
    link="https://mp.weixin.qq.com/s/test?b=2&a=1#fragment",
    published="Sat, 11 Jul 2026 10:00:00 GMT",
    updated=None,
    author="作者",
    digest="摘要",
)
NOW = datetime(2026, 7, 11, 18, 5, tzinfo=timezone.utc)


def test_map_item_uses_configured_account_and_shanghai_publish_time():
    raw = map_feed_item(item=ITEM, account_name="示例公众号", batch_id="b1", collect_time=NOW)
    assert raw.account_name == "示例公众号"
    assert raw.publish_time == datetime(2026, 7, 11, 18, 0)
    assert raw.publish_time.tzinfo is None
    assert raw.article_url == "https://mp.weixin.qq.com/s/test?a=1&b=2"
    assert raw.collect_time == NOW


@pytest.mark.parametrize("field", ["title", "link"])
def test_map_item_rejects_missing_required_field(field):
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, **{field: None}), account_name="a", batch_id="b", collect_time=NOW)


def test_map_item_uses_updated_when_published_is_blank():
    item = replace(ITEM, published=" ", updated="2026-07-11T10:00:00Z")
    assert map_feed_item(item=item, account_name="a", batch_id="b", collect_time=NOW).publish_time == datetime(2026, 7, 11, 18)


def test_map_item_uses_updated_when_published_is_none():
    item = replace(ITEM, published=None, updated="2026-07-11T10:00:00Z")
    assert map_feed_item(item=item, account_name="a", batch_id="b", collect_time=NOW).publish_time == datetime(2026, 7, 11, 18)


def test_map_item_uses_updated_when_published_is_invalid():
    item = replace(ITEM, published="not-a-date", updated="2026-07-11T10:00:00Z")
    assert map_feed_item(item=item, account_name="a", batch_id="b", collect_time=NOW).publish_time == datetime(2026, 7, 11, 18)


def test_map_item_rejects_when_both_publish_times_are_absent_or_invalid():
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, published=None, updated="bad"), account_name="a", batch_id="b", collect_time=NOW)


@pytest.mark.parametrize("url", ["https://example.com/s/a", "https://mp.weixin.qq.com/mp/profile_ext?action=home"])
def test_map_item_rejects_non_wechat_article_url(url):
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, link=url), account_name="a", batch_id="b", collect_time=NOW)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@mp.weixin.qq.com/s/a",
        "https://mp.weixin.qq.com:444/s/a",
        "https://mp.weixin.qq.com:443/s/a",
        "https://mp.weixin.qq.com/s/../not-article",
        "https://mp.weixin.qq.com/s/",
        "https://mp.weixin.qq.com/s/./a",
        "https://mp.weixin.qq.com/s/%2e%2e%2fnot-article",
        "https://mp.weixin.qq.com/s/%2e%2e%5cnot-article",
        "https://mp.weixin.qq.com/s/a%2fb",
    ],
)
def test_map_item_rejects_ambiguous_or_malicious_article_url(url):
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, link=url), account_name="a", batch_id="b", collect_time=NOW)


def test_map_item_hash_is_stable_across_query_order_and_fragment():
    first = map_feed_item(item=ITEM, account_name="a", batch_id="b", collect_time=NOW)
    equivalent = replace(ITEM, link="https://mp.weixin.qq.com/s/test?a=1&b=2#other")
    second = map_feed_item(item=equivalent, account_name="a", batch_id="b", collect_time=NOW)
    assert first.article_hash == second.article_hash
    assert first.article_url == second.article_url
