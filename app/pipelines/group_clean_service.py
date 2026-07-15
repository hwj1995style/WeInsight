from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.group_cleaning import CleanGroupMessage, clean_raw_group_message
from app.domain.group_messages import RawGroupMessage


@dataclass(frozen=True)
class GroupCleanResult:
    read_count: int
    success_count: int
    failed_count: int


class GroupCleanRepo(Protocol):
    def list_pending_clean_raw_messages(self, limit: int) -> list[RawGroupMessage]:
        ...

    def upsert_clean_message(self, message: CleanGroupMessage) -> None:
        ...

    def create_analyze_task(self, msg_hash: str) -> None:
        ...

    def mark_clean_task_success(self, msg_hash: str) -> None:
        ...

    def mark_clean_task_failed(self, msg_hash: str, error_msg: str) -> None:
        ...


class GroupCleanService:
    def __init__(self, *, repo: GroupCleanRepo) -> None:
        self.repo = repo

    def clean_once(self, limit: int, clean_time: datetime) -> GroupCleanResult:
        raws = self.repo.list_pending_clean_raw_messages(limit)
        success_count = 0
        failed_count = 0

        for raw in raws:
            try:
                clean = clean_raw_group_message(raw, clean_time=clean_time)
                self.repo.upsert_clean_message(clean)
                self.repo.create_analyze_task(raw.msg_hash)
                self.repo.mark_clean_task_success(raw.msg_hash)
                success_count += 1
            except Exception as exc:
                self.repo.mark_clean_task_failed(raw.msg_hash, str(exc))
                failed_count += 1

        return GroupCleanResult(
            read_count=len(raws),
            success_count=success_count,
            failed_count=failed_count,
        )
