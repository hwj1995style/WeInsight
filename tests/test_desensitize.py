from __future__ import annotations

from app.domain.desensitize import mask_phone, mask_wechat_id


def test_mask_phone() -> None:
    assert mask_phone("联系人 13812345678") == "联系人 138****5678"


def test_mask_wechat_id() -> None:
    assert mask_wechat_id("微信 wxid_abc123 可联系") == "微信 [微信号已脱敏] 可联系"
