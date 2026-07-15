from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.domain.group_messages import CollectResult
from app.pipelines.group_polling_runner import GroupPollingRunner, GroupPollingTarget
from app.storage.lock_repo import InMemoryUiLockRepo


class FakeCollectService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime]] = []
        self.fail_with: Exception | None = None

    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime) -> CollectResult:
        self.calls.append((group_name, batch_id, collect_time))
        if self.fail_with is not None:
            raise self.fail_with
        return CollectResult(
            group_name=group_name,
            batch_id=batch_id,
            read_count=2,
            insert_count=1,
            duplicate_count=1,
        )


class FakeLogRepo:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def insert_collect_log(self, record) -> None:
        self.records.append(record.__dict__)

    def mark_group_collect_failed(self, group_name: str, error_msg: str) -> None:
        self.records.append({"cursor_failed_group": group_name, "error_msg": error_msg})


class FakeScreenshotClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def save_screenshot(self, path: str) -> str:
        self.paths.append(path)
        return path


def test_group_polling_runner_collects_due_groups_with_ui_lock(tmp_path: Path) -> None:
    now = datetime(2026, 7, 3, 9, 0, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeCollectService()
    log_repo = FakeLogRepo()
    screenshot_client = FakeScreenshotClient()
    runner = GroupPollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        group_provider=lambda current, limit: [
            GroupPollingTarget("核心群B", priority=1, poll_interval_seconds=30),
            GroupPollingTarget("核心群A", priority=2, poll_interval_seconds=30),
        ],
        log_repo=log_repo,
        screenshot_client=screenshot_client,
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_groups_per_round=5,
        batch_id_factory=lambda group_name: f"batch-{group_name}",
    )

    result = runner.run_once(now)

    assert result.success_count == 2
    assert result.read_count == 4
    assert result.insert_count == 2
    assert result.duplicate_count == 2
    assert result.error_code is None
    assert result.screenshot_path is None
    assert [call[0] for call in collect_service.calls] == ["核心群B", "核心群A"]
    assert lock_repo.current_owner("wechat_ui") is None
    assert [record["status"] for record in log_repo.records] == ["success", "success"]
    assert screenshot_client.paths == []


def test_group_polling_runner_does_not_open_wechat_when_ui_lock_is_busy(tmp_path: Path) -> None:
    now = datetime(2026, 7, 3, 9, 0, 0)
    lock_repo = InMemoryUiLockRepo()
    assert lock_repo.acquire("wechat_ui", "article", "article-1", now, 120) is True
    collect_service = FakeCollectService()
    log_repo = FakeLogRepo()
    runner = GroupPollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        group_provider=lambda current, limit: [GroupPollingTarget("核心群A", 1, 30)],
        log_repo=log_repo,
        screenshot_client=FakeScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_groups_per_round=5,
        batch_id_factory=lambda group_name: "batch-lock-busy",
    )

    result = runner.run_once(now)

    assert result.lock_timeout_count == 1
    assert result.error_code == "WECHAT_UI_LOCK_TIMEOUT"
    assert result.error_summary is not None
    assert result.screenshot_path is None
    assert collect_service.calls == []
    assert lock_repo.current_owner("wechat_ui") == "article"
    assert log_repo.records[0]["status"] == "failed"
    assert log_repo.records[0]["error_code"] == "WECHAT_UI_LOCK_TIMEOUT"
    assert log_repo.records[0]["screenshot_path"] is None


def test_group_polling_runner_saves_screenshot_and_releases_lock_on_rpa_error(tmp_path: Path) -> None:
    now = datetime(2026, 7, 3, 9, 0, 0)
    lock_repo = InMemoryUiLockRepo()
    collect_service = FakeCollectService()
    collect_service.fail_with = RuntimeError("boom")
    log_repo = FakeLogRepo()
    screenshot_client = FakeScreenshotClient()
    runner = GroupPollingRunner(
        collect_service=collect_service,
        lock_repo=lock_repo,
        group_provider=lambda current, limit: [GroupPollingTarget("核心群A", 1, 30)],
        log_repo=log_repo,
        screenshot_client=screenshot_client,
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=120,
        lock_acquire_timeout_seconds=0,
        max_groups_per_round=5,
        batch_id_factory=lambda group_name: "batch-rpa-error",
    )

    result = runner.run_once(now)

    assert result.failed_count == 1
    assert result.error_code == "WECHAT_RPA_ERROR"
    assert result.error_summary == "boom"
    assert result.screenshot_path == screenshot_client.paths[0]
    assert lock_repo.current_owner("wechat_ui") is None
    assert len(screenshot_client.paths) == 1
    assert screenshot_client.paths[0].endswith("runtime/screenshots/group/20260703/batch-rpa-error.png")
    assert log_repo.records[0]["status"] == "failed"
    assert log_repo.records[0]["error_code"] == "WECHAT_RPA_ERROR"
    assert log_repo.records[0]["screenshot_path"] == screenshot_client.paths[0]
    assert log_repo.records[1]["cursor_failed_group"] == "核心群A"
