from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.domain.desensitize import contains_phone, contains_wechat_id, mask_phone, mask_wechat_id
from app.domain.group_messages import RawGroupMessage


@dataclass(frozen=True)
class CleanGroupMessage:
    msg_hash: str
    group_name: str
    sender_hash: str | None
    sender_display: str
    msg_time_display: str
    msg_time_inferred: datetime | None
    msg_type: str
    clean_content: str
    content_length: int
    is_empty: bool
    has_phone: bool
    has_wechat_id: bool
    clean_version: str
    source_collect_batch_id: str
    clean_time: datetime


def clean_raw_group_message(raw: RawGroupMessage, clean_time: datetime) -> CleanGroupMessage:
    content = (raw.msg_content or "").strip()
    has_phone = contains_phone(content)
    has_wechat_id = contains_wechat_id(content)
    clean_content = mask_wechat_id(mask_phone(content)).strip()
    sender_name = (raw.sender_name or "").strip()

    return CleanGroupMessage(
        msg_hash=raw.msg_hash,
        group_name=raw.group_name,
        sender_hash=_sender_hash(raw.group_name, sender_name) if sender_name else None,
        sender_display=_sender_display(sender_name),
        msg_time_display=raw.msg_time_display,
        msg_time_inferred=None,
        msg_type=raw.msg_type,
        clean_content=clean_content,
        content_length=len(clean_content),
        is_empty=clean_content == "",
        has_phone=has_phone,
        has_wechat_id=has_wechat_id,
        clean_version="v1",
        source_collect_batch_id=raw.collect_batch_id,
        clean_time=clean_time,
    )


def _sender_hash(group_name: str, sender_name: str) -> str:
    value = f"{group_name}\u241f{sender_name}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sender_display(sender_name: str) -> str:
    if not sender_name:
        return ""
    return f"{sender_name[0]}***"
