from __future__ import annotations

from datetime import datetime

from app.domain.group_messages import CollectResult, GroupCursor, RawGroupMessage
from app.domain.hashes import group_msg_hash
from app.rpa.interfaces import WechatGroupRpaClient
from app.storage.group_repo import GroupMessageRepo


class GroupCollectService:
    def __init__(self, *, rpa: WechatGroupRpaClient, repo: GroupMessageRepo) -> None:
        self.rpa = rpa
        self.repo = repo

    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime) -> CollectResult:
        self.rpa.open_group(group_name)
        visible_messages = self.rpa.read_visible_messages()
        raw_messages: list[RawGroupMessage] = []

        for visible in visible_messages:
            msg_hash = group_msg_hash(
                group_name=visible.group_name,
                sender_name=visible.sender_name,
                msg_time_display=visible.msg_time_display,
                msg_content=visible.msg_content,
                msg_type=visible.msg_type,
            )
            raw_messages.append(
                RawGroupMessage(
                    msg_hash=msg_hash,
                    group_name=visible.group_name,
                    sender_name=visible.sender_name,
                    msg_time_display=visible.msg_time_display,
                    msg_type=visible.msg_type,
                    msg_content=visible.msg_content,
                    raw_content=visible.msg_content,
                    collect_time=collect_time,
                    collect_batch_id=batch_id,
                )
            )

        inserted_count = self.repo.insert_raw_ignore_duplicates(raw_messages)

        if raw_messages:
            newest = raw_messages[-1]
            self.repo.update_cursor(
                GroupCursor(
                    group_name=group_name,
                    last_msg_hash=newest.msg_hash,
                    last_msg_time_display=newest.msg_time_display,
                    last_msg_content_preview=newest.msg_content[:500],
                    last_sender_name=newest.sender_name,
                    last_success_collect_time=collect_time,
                    last_collect_batch_id=batch_id,
                )
            )

        return CollectResult(
            group_name=group_name,
            batch_id=batch_id,
            read_count=len(visible_messages),
            insert_count=inserted_count,
            duplicate_count=len(raw_messages) - inserted_count,
        )
