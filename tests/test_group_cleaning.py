from __future__ import annotations

from datetime import datetime

from app.domain.group_cleaning import clean_raw_group_message
from app.domain.group_messages import RawGroupMessage


def test_clean_raw_group_message_masks_sensitive_content_and_sender() -> None:
    raw = RawGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_name="张三",
        msg_time_display="08:31",
        msg_type="text",
        msg_content="联系 13812345678 微信 wxid_abc123",
        raw_content="联系 13812345678 微信 wxid_abc123",
        collect_time=datetime(2026, 7, 3, 9, 0, 0),
        collect_batch_id="batch-1",
    )

    clean = clean_raw_group_message(raw, clean_time=datetime(2026, 7, 3, 9, 1, 0))

    assert clean.msg_hash == "hash-1"
    assert clean.group_name == "核心群A"
    assert clean.sender_hash
    assert clean.sender_display == "张***"
    assert clean.clean_content == "联系 138****5678 微信 [微信号已脱敏]"
    assert clean.has_phone is True
    assert clean.has_wechat_id is True
    assert clean.is_empty is False
    assert clean.source_collect_batch_id == "batch-1"


def test_clean_raw_group_message_marks_empty_content() -> None:
    raw = RawGroupMessage(
        msg_hash="hash-2",
        group_name="核心群A",
        sender_name="",
        msg_time_display="08:32",
        msg_type="text",
        msg_content="   ",
        raw_content="   ",
        collect_time=datetime(2026, 7, 3, 9, 0, 0),
        collect_batch_id="batch-1",
    )

    clean = clean_raw_group_message(raw, clean_time=datetime(2026, 7, 3, 9, 1, 0))

    assert clean.sender_display == ""
    assert clean.clean_content == ""
    assert clean.content_length == 0
    assert clean.is_empty is True
