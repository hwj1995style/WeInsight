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


@pytest.mark.parametrize("field", ["title", "link", "published"])
def test_map_item_rejects_missing_required_field(field):
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, **{field: None}), account_name="a", batch_id="b", collect_time=NOW)


def test_map_item_uses_updated_when_published_is_blank():
    item = replace(ITEM, published=" ", updated="2026-07-11T10:00:00Z")
    assert map_feed_item(item=item, account_name="a", batch_id="b", collect_time=NOW).publish_time == datetime(2026, 7, 11, 18)


@pytest.mark.parametrize("url", ["https://example.com/s/a", "https://mp.weixin.qq.com/mp/profile_ext?action=home"])
def test_map_item_rejects_non_wechat_article_url(url):
    with pytest.raises(FeedItemInvalid):
        map_feed_item(item=replace(ITEM, link=url), account_name="a", batch_id="b", collect_time=NOW)
