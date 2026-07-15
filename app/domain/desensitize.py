from __future__ import annotations

import re


PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
WECHAT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:wxid_[A-Za-z0-9_-]+|[A-Za-z][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_])"
)


def mask_phone(text: str) -> str:
    return PHONE_PATTERN.sub(r"\1****\3", text)


def mask_wechat_id(text: str) -> str:
    return WECHAT_ID_PATTERN.sub("[微信号已脱敏]", text)


def contains_phone(text: str) -> bool:
    return PHONE_PATTERN.search(text) is not None


def contains_wechat_id(text: str) -> bool:
    return WECHAT_ID_PATTERN.search(text) is not None
