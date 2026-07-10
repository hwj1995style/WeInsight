from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawGroupMessage:
    msg_hash: str
    group_name: str
    sender_name: str
    msg_time_display: str
    msg_type: str
    msg_content: str
    raw_content: str
    collect_time: datetime
    collect_batch_id: str


@dataclass(frozen=True)
class GroupCursor:
    group_name: str
    last_msg_hash: str
    last_msg_time_display: str
    last_msg_content_preview: str
    last_sender_name: str
    last_success_collect_time: datetime
    last_collect_batch_id: str


@dataclass(frozen=True)
class CollectResult:
    group_name: str
    batch_id: str
    read_count: int
    insert_count: int
    duplicate_count: int
