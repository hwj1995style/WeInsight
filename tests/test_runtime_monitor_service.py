from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType, RunStatus
from app.services.runtime_monitor_service import (
    EventListFilter,
    RunListFilter,
    RuntimeEvent,
    RuntimeMonitorService,
    TargetRunDetail,
    UiLockView,
    WechatHealthView,
    WorkerHeartbeatView,
    WorkerMonitorSnapshot,
)
from app.rpa.desktop_probe import WechatHealthStatus


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 12, 30, tzinfo=ZONE)


class Repo:
    def __init__(self) -> None:
        self.calls = []
        self.run_page = PagedResult([], 1, 20, 0)
        self.event_page = PagedResult([], 1, 50, 0)
        self.detail = None

    def list_runs(self, filters, page, page_size):
        self.calls.append(("list_runs", filters, page, page_size))
        return self.run_page

    def list_events(self, filters, page, page_size):
        self.calls.append(("list_events", filters, page, page_size))
        return self.event_page

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return self.detail


def test_run_and_event_filters_validate_allowlisted_types(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    run_filters = RunListFilter(
        pipeline_type=PipelineType.GROUP,
        status=RunStatus.RUNNING,
        run_date=date(2026, 7, 10),
        job_id=7,
        job_name="晨间",
    )
    event_filters = EventListFilter(
        job_id=7,
        run_id=11,
        target_run_id=13,
        pipeline_type=PipelineType.GROUP,
        level="warning",
        start_at=NOW - timedelta(hours=1),
        end_at=NOW,
    )

    assert service.list_runs(run_filters, 1, 20).total_count == 0
    assert service.list_events(event_filters, 1, 50).total_count == 0

    with pytest.raises(ValueError):
        service.list_runs(RunListFilter(job_name="x" * 201), 1, 20)
    with pytest.raises(ValueError):
        service.list_runs(RunListFilter(run_date=NOW), 1, 20)
    with pytest.raises(ValueError):
        service.list_events(EventListFilter(level="fatal"), 1, 50)
    with pytest.raises(ValueError):
        service.list_events(
            EventListFilter(
                start_at=datetime(2026, 7, 10, 9, 0),
                end_at=NOW,
            ),
            1,
            50,
        )


@pytest.mark.parametrize(
    ("raw_path", "expected_valid"),
    [
        ("inside/failure.png", False),
        (None, True),
        (123, False),
    ],
)
def test_screenshot_path_requires_absolute_path(
    tmp_path: Path, raw_path, expected_valid: bool
) -> None:
    root = tmp_path / "screenshots"
    root.mkdir()
    service = RuntimeMonitorService(Repo(), root, heartbeat_ttl_seconds=30)

    value = service.safe_screenshot_path(raw_path)

    if raw_path is None:
        assert value is None
    elif expected_valid:
        assert value != "截图路径无效"
    else:
        assert value == "截图路径无效"


def test_screenshot_path_allows_only_resolved_absolute_path_under_root(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "screenshots").resolve()
    root.mkdir()
    service = RuntimeMonitorService(Repo(), root, heartbeat_ttl_seconds=30)
    valid = root / "group" / "missing.png"
    outside = root.parent / "screenshots-other" / "secret.png"
    traversal = root / ".." / "secret.png"

    assert service.safe_screenshot_path(str(valid)) == str(valid.resolve())
    assert service.safe_screenshot_path(str(outside)) == "截图路径无效"
    assert service.safe_screenshot_path(str(traversal)) == "截图路径无效"


def test_screenshot_path_resolves_symlink_before_root_check(tmp_path: Path) -> None:
    root = (tmp_path / "screenshots").resolve()
    outside = (tmp_path / "outside").resolve()
    root.mkdir()
    outside.mkdir()
    link = root / "linked-outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    service = RuntimeMonitorService(Repo(), root, heartbeat_ttl_seconds=30)

    assert service.safe_screenshot_path(str(link / "secret.png")) == "截图路径无效"


def test_target_screenshot_output_never_preserves_invalid_raw_value(
    tmp_path: Path,
) -> None:
    service = RuntimeMonitorService(
        Repo(), tmp_path / "screenshots", heartbeat_ttl_seconds=30
    )
    target = TargetRunDetail(
        id=1,
        job_target_id=2,
        target_name="核心群",
        status="failed",
        stage="copy",
        batch_id="batch-1",
        read_count=1,
        insert_count=0,
        duplicate_count=0,
        skipped_count=0,
        error_code="E_RPA",
        error_summary="<b>13812345678</b> https://example.com/raw",
        screenshot_path="D:\\outside\\secret.png",
        start_time=NOW,
        end_time=NOW,
    )

    safe = service.safe_target(target)

    assert safe.screenshot_path == "截图路径无效"
    assert "D:\\outside" not in safe.screenshot_path
    assert "13812345678" not in (safe.error_summary or "")
    assert "https://" not in (safe.error_summary or "")


def test_event_and_worker_control_labels_are_sanitized_on_read(tmp_path: Path) -> None:
    repo = Repo()
    repo.event_page = PagedResult(
        [
            RuntimeEvent(
                id=1,
                job_id=7,
                run_id=11,
                target_run_id=13,
                pipeline_type=PipelineType.GROUP,
                worker_id="<b>worker</b>",
                level="error",
                event_type="<i>event</i>",
                stage="<u>stage</u>",
                message="safe",
                metrics_summary="{}",
                actor_type="worker",
                actor_name="<script>actor</script>",
                create_time=NOW,
            )
        ],
        1,
        50,
        1,
    )
    repo.worker_snapshot = WorkerMonitorSnapshot(
        workers=(
            WorkerHeartbeatView(
                "worker-1",
                "collector",
                "<b>HOST</b>",
                123,
                "<i>v1</i>",
                "running",
                NOW,
                NOW,
                "safe",
                True,
            ),
        ),
        health_checks=(
            WechatHealthView(
                "<b>HOST</b>",
                WechatHealthStatus.OK,
                "<i>4.1</i>",
                0,
                "safe",
                NOW,
            ),
        ),
        ui_lock=UiLockView("free"),
        checked_at=NOW,
    )

    def get_worker_snapshot(now, ttl):
        return repo.worker_snapshot

    repo.get_worker_snapshot = get_worker_snapshot
    service = RuntimeMonitorService(repo, tmp_path, heartbeat_ttl_seconds=30)

    event = service.list_events(EventListFilter(), 1, 50).items[0]
    workers = service.get_workers(NOW)

    for value in (
        event.worker_id,
        event.event_type,
        event.stage,
        event.actor_name,
        workers.workers[0].hostname,
        workers.workers[0].version,
        workers.health_checks[0].hostname,
        workers.health_checks[0].detected_version,
    ):
        assert value is not None
        assert "<" not in value and ">" not in value
