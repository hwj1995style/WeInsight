from __future__ import annotations

from datetime import datetime

from app.pipelines.group_collect_service import GroupCollectService
from app.rpa.fake_clients import FakeGroupRpaClient
from app.rpa.interfaces import VisibleMessage
from app.storage.group_repo import InMemoryGroupMessageRepo


def test_group_collect_service_inserts_raw_messages_and_updates_cursor() -> None:
    messages = [
        VisibleMessage("核心群A", "张三", "08:31", "求购鸡蛋 30 箱"),
        VisibleMessage("核心群A", "李四", "08:32", "供应鸡蛋 20 箱"),
    ]
    repo = InMemoryGroupMessageRepo()
    service = GroupCollectService(rpa=FakeGroupRpaClient(messages), repo=repo)

    result = service.collect_once(
        group_name="核心群A",
        batch_id="batch-1",
        collect_time=datetime(2026, 7, 2, 8, 33, 0),
    )

    assert result.read_count == 2
    assert result.insert_count == 2
    assert repo.cursor_by_group["核心群A"].last_msg_content_preview == "供应鸡蛋 20 箱"


def test_group_collect_service_ignores_duplicate_messages() -> None:
    message = VisibleMessage("核心群A", "张三", "08:31", "求购鸡蛋 30 箱")
    repo = InMemoryGroupMessageRepo()
    service = GroupCollectService(rpa=FakeGroupRpaClient([message]), repo=repo)

    first = service.collect_once("核心群A", "batch-1", datetime(2026, 7, 2, 8, 33, 0))
    second = service.collect_once("核心群A", "batch-2", datetime(2026, 7, 2, 8, 34, 0))

    assert first.insert_count == 1
    assert second.insert_count == 0
    assert len(repo.messages_by_hash) == 1
