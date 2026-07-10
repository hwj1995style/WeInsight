from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.domain.group_messages import CollectResult
from app.storage.group_repo import GroupCollectLogRecord


@dataclass(frozen=True)
class GroupPollingTarget:
    group_name: str
    priority: int
    poll_interval_seconds: int


@dataclass(frozen=True)
class GroupPollingRunResult:
    attempted_count: int
    success_count: int
    failed_count: int
    lock_timeout_count: int
    read_count: int = 0
    insert_count: int = 0
    duplicate_count: int = 0
    error_code: str | None = None
    error_summary: str | None = None
    screenshot_path: str | None = None


class CollectService(Protocol):
    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime) -> CollectResult:
        ...


class UiLockRepo(Protocol):
    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        ...

    def release(self, lock_name: str, owner_pipeline: str, owner_task_id: str) -> bool:
        ...


class GroupCollectLogRepo(Protocol):
    def insert_collect_log(self, record: GroupCollectLogRecord) -> None:
        ...

    def mark_group_collect_failed(self, group_name: str, error_msg: str) -> None:
        ...


class ScreenshotClient(Protocol):
    def save_screenshot(self, path: str) -> str:
        ...


class GroupPollingRunner:
    def __init__(
        self,
        *,
        collect_service: CollectService,
        lock_repo: UiLockRepo,
        group_provider: Callable[[datetime, int], Iterable[GroupPollingTarget]],
        log_repo: GroupCollectLogRepo,
        screenshot_client: ScreenshotClient,
        screenshot_root: Path,
        lease_seconds: int,
        lock_acquire_timeout_seconds: int,
        max_groups_per_round: int,
        batch_id_factory: Callable[[str], str],
    ) -> None:
        self.collect_service = collect_service
        self.lock_repo = lock_repo
        self.group_provider = group_provider
        self.log_repo = log_repo
        self.screenshot_client = screenshot_client
        self.screenshot_root = screenshot_root
        self.lease_seconds = lease_seconds
        self.lock_acquire_timeout_seconds = lock_acquire_timeout_seconds
        self.max_groups_per_round = max_groups_per_round
        self.batch_id_factory = batch_id_factory

    def run_once(self, now: datetime) -> GroupPollingRunResult:
        targets = sorted(
            self.group_provider(now, self.max_groups_per_round),
            key=lambda item: (item.priority, item.group_name),
        )[: self.max_groups_per_round]

        success_count = 0
        failed_count = 0
        lock_timeout_count = 0
        read_count = 0
        insert_count = 0
        duplicate_count = 0
        error_code = None
        error_summary = None
        screenshot_path_value = None

        for target in targets:
            batch_id = self.batch_id_factory(target.group_name)
            start_time = now
            acquired = self.lock_repo.acquire(
                lock_name="wechat_ui",
                owner_pipeline="group",
                owner_task_id=batch_id,
                now=now,
                lease_seconds=self.lease_seconds,
            )
            if not acquired:
                lock_timeout_count += 1
                error_code = "WECHAT_UI_LOCK_TIMEOUT"
                error_summary = (
                    "Failed to acquire wechat_ui lock within "
                    f"{self.lock_acquire_timeout_seconds} seconds."
                )
                self.log_repo.insert_collect_log(
                    GroupCollectLogRecord(
                        batch_id=batch_id,
                        source_name=target.group_name,
                        start_time=start_time,
                        end_time=now,
                        status="failed",
                        error_code="WECHAT_UI_LOCK_TIMEOUT",
                        error_msg=(
                            "Failed to acquire wechat_ui lock within "
                            f"{self.lock_acquire_timeout_seconds} seconds."
                        ),
                    )
                )
                continue

            try:
                result = self.collect_service.collect_once(target.group_name, batch_id, now)
                success_count += 1
                read_count += result.read_count
                insert_count += result.insert_count
                duplicate_count += result.duplicate_count
                self.log_repo.insert_collect_log(
                    GroupCollectLogRecord(
                        batch_id=batch_id,
                        source_name=target.group_name,
                        start_time=start_time,
                        end_time=now,
                        read_count=result.read_count,
                        insert_count=result.insert_count,
                        duplicate_count=result.duplicate_count,
                        status="success",
                    )
                )
            except Exception as exc:
                failed_count += 1
                error_code = "WECHAT_RPA_ERROR"
                error_summary = str(exc)
                screenshot_path = self._screenshot_path(batch_id, now)
                saved_screenshot_path = self.screenshot_client.save_screenshot(screenshot_path.as_posix())
                screenshot_path_value = saved_screenshot_path
                self.log_repo.insert_collect_log(
                    GroupCollectLogRecord(
                        batch_id=batch_id,
                        source_name=target.group_name,
                        start_time=start_time,
                        end_time=now,
                        status="failed",
                        error_code="WECHAT_RPA_ERROR",
                        error_msg=str(exc),
                        screenshot_path=saved_screenshot_path,
                    )
                )
                self.log_repo.mark_group_collect_failed(target.group_name, str(exc))
            finally:
                self.lock_repo.release("wechat_ui", "group", batch_id)

        return GroupPollingRunResult(
            attempted_count=len(targets),
            success_count=success_count,
            failed_count=failed_count,
            lock_timeout_count=lock_timeout_count,
            read_count=read_count,
            insert_count=insert_count,
            duplicate_count=duplicate_count,
            error_code=error_code,
            error_summary=error_summary,
            screenshot_path=screenshot_path_value,
        )

    def _screenshot_path(self, batch_id: str, now: datetime) -> Path:
        return self.screenshot_root / "group" / now.strftime("%Y%m%d") / f"{batch_id}.png"
