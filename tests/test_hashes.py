from __future__ import annotations

from app.domain.hashes import article_hash, group_msg_hash


def test_group_msg_hash_is_stable() -> None:
    first = group_msg_hash(
        group_name="核心交易群A",
        sender_name="张三",
        msg_time_display="2026-07-02 08:31",
        msg_content="求购鸡蛋 30 箱 北京",
        msg_type="text",
    )
    second = group_msg_hash(
        group_name="核心交易群A",
        sender_name="张三",
        msg_time_display="2026-07-02 08:31",
        msg_content="求购鸡蛋 30 箱 北京",
        msg_type="text",
    )

    assert first == second
    assert len(first) == 64


def test_article_hash_is_stable() -> None:
    value = article_hash(
        account_name="行业观察",
        title="鸡蛋市场日报",
        publish_time="2026-07-02 08:00:00",
        url="https://mp.weixin.qq.com/s/example",
    )

    assert len(value) == 64
