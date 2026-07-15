from __future__ import annotations

from datetime import datetime

from app.domain.group_cleaning import CleanGroupMessage
from app.domain.group_messages import RawGroupMessage
from app.pipelines.group_clean_service import GroupCleanService


class FakeCleanRepo:
    def __init__(self, raws: list[RawGroupMessage]) -> None:
        self.raws = raws
        self.clean_messages: list[CleanGroupMessage] = []
        self.successes: list[str] = []
        self.failures: list[tuple[str, str]] = []
        self.analyze_tasks: list[str] = []

    def list_pending_clean_raw_messages(self, limit: int) -> list[RawGroupMessage]:
        return self.raws[:limit]

    def upsert_clean_message(self, message: CleanGroupMessage) -> None:
        self.clean_messages.append(message)

    def create_analyze_task(self, msg_hash: str) -> None:
        self.analyze_tasks.append(msg_hash)

    def mark_clean_task_success(self, msg_hash: str) -> None:
        self.successes.append(msg_hash)

    def mark_clean_task_failed(self, msg_hash: str, error_msg: str) -> None:
        self.failures.append((msg_hash, error_msg))


def test_group_clean_service_cleans_pending_raw_messages() -> None:
    raw = RawGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_name="张三",
        msg_time_display="08:31",
        msg_type="text",
        msg_content="联系 13812345678",
        raw_content="联系 13812345678",
        collect_time=datetime(2026, 7, 3, 9, 0, 0),
        collect_batch_id="batch-1",
    )
    repo = FakeCleanRepo([raw])
    service = GroupCleanService(repo=repo)

    result = service.clean_once(limit=10, clean_time=datetime(2026, 7, 3, 9, 1, 0))

    assert result.read_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    assert repo.clean_messages[0].clean_content == "联系 138****5678"
    assert repo.analyze_tasks == ["hash-1"]
    assert repo.successes == ["hash-1"]
