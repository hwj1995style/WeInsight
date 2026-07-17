from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import json
from zoneinfo import ZoneInfo

import pytest

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import PipelineType, RunStatus
from app.services.runtime_monitor_service import (
    EventListFilter,
    RunListFilter,
    RunDetail,
    RunNotFoundError,
    RunOutsideVisibilityError,
    RunSummary,
    RuntimeDashboardSnapshot,
    RuntimeEvent,
    RuntimeMonitorService,
    runtime_visibility_start,
    TargetRunDetail,
    UiLockView,
    WechatHealthView,
    WorkerHeartbeatView,
    WorkerMonitorSnapshot,
)
from app.rpa.desktop_probe import WechatHealthStatus


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 12, 30, tzinfo=ZONE)


def test_empty_dashboard_does_not_report_ui_lock_as_free() -> None:
    snapshot = RuntimeDashboardSnapshot.empty(NOW)

    assert snapshot.ui_lock_state == "unavailable"


class Repo:
    def __init__(self) -> None:
        self.calls = []
        self.run_page = PagedResult([], 1, 20, 0)
        self.event_page = PagedResult([], 1, 50, 0)
        self.detail = None

    def list_runs(self, filters, page, page_size, visible_since):
        self.calls.append(("list_runs", filters, page, page_size, visible_since))
        return self.run_page

    def list_events(self, filters, page, page_size, visible_since):
        self.calls.append(("list_events", filters, page, page_size, visible_since))
        return self.event_page

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return self.detail


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 7, 13, 12, 34, 56, 789, tzinfo=ZONE),
            datetime(2026, 4, 13, 12, 34, 56, 789, tzinfo=ZONE),
        ),
        (
            datetime(2026, 5, 31, 8, 9, tzinfo=ZONE),
            datetime(2026, 2, 28, 8, 9, tzinfo=ZONE),
        ),
        (
            datetime(2024, 5, 31, 8, 9, tzinfo=ZONE),
            datetime(2024, 2, 29, 8, 9, tzinfo=ZONE),
        ),
    ],
)
def test_runtime_visibility_start_rolls_back_three_calendar_months(now, expected) -> None:
    assert runtime_visibility_start(now) == expected


def test_runtime_visibility_start_rejects_naive_now() -> None:
    with pytest.raises(ValueError):
        runtime_visibility_start(datetime(2026, 7, 13, 12, 0))


def test_runtime_monitor_service_rejects_noncallable_clock(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="now_provider"):
        RuntimeMonitorService(
            Repo(), tmp_path, heartbeat_ttl_seconds=30, now_provider=NOW
        )


def test_list_calls_read_clock_once_and_apply_visibility_boundary(tmp_path: Path) -> None:
    repo = Repo()
    calls = 0

    def now_provider():
        nonlocal calls
        calls += 1
        return datetime(2026, 7, 13, 12, 0, tzinfo=ZONE)

    service = RuntimeMonitorService(
        repo, tmp_path, heartbeat_ttl_seconds=30, now_provider=now_provider
    )
    service.list_runs(RunListFilter(), 1, 20)
    assert calls == 1
    assert repo.calls[-1][-1] == datetime(2026, 4, 13, 12, 0, tzinfo=ZONE)

    service.list_events(
        EventListFilter(start_at=datetime(2026, 1, 1, tzinfo=ZONE)), 1, 50
    )
    assert calls == 2
    assert repo.calls[-1][1].start_at == datetime(2026, 4, 13, 12, 0, tzinfo=ZONE)
    assert repo.calls[-1][-1] == datetime(2026, 4, 13, 12, 0, tzinfo=ZONE)

    later = datetime(2026, 6, 1, tzinfo=ZONE)
    service.list_events(EventListFilter(start_at=later, end_at=NOW), 1, 50)
    assert repo.calls[-1][1].start_at == later
    assert repo.calls[-1][1].end_at == NOW


def _detail_at(scheduled_at: datetime) -> RunDetail:
    return RunDetail(
        run=RunSummary(31, 7, "secret job", PipelineType.GROUP, scheduled_at,
                       RunStatus.FAILED, "secret-worker", None, None, 0, 0, 0),
        hostname=None, lease_expires_at=None, error_code=None,
        error_summary="secret failure", targets=(),
    )


def test_get_run_enforces_visibility_boundary_without_leaking_detail(tmp_path: Path) -> None:
    boundary = datetime(2026, 4, 13, 12, 0, tzinfo=ZONE)
    repo = Repo()
    service = RuntimeMonitorService(
        repo, tmp_path, heartbeat_ttl_seconds=30,
        now_provider=lambda: datetime(2026, 7, 13, 12, 0, tzinfo=ZONE),
    )
    repo.detail = _detail_at(boundary)
    assert service.get_run(31).run.scheduled_at == boundary

    repo.detail = _detail_at(boundary - timedelta(microseconds=1))
    with pytest.raises(RunOutsideVisibilityError) as caught:
        service.get_run(31)
    message = str(caught.value)
    assert "secret job" not in message
    assert "secret-worker" not in message
    assert "secret failure" not in message

    repo.detail = None
    with pytest.raises(RunNotFoundError):
        service.get_run(31)


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


@pytest.mark.parametrize(
    ("event_type", "summary"),
    [
        ("collection_run_started", "开始执行采集任务"),
        ("collection_run_finished", "本轮采集完成"),
        ("collection_run_claimed", "已领取采集运行"),
        ("collection_run_lease_expired", "采集运行租约已过期"),
        ("collection_target_started", "开始处理目标"),
        ("collection_target_finished", "目标处理完成"),
        ("job_created", "已创建采集任务"),
        ("job_started", "已启动采集任务"),
        ("job_updated", "已更新采集任务"),
        ("job_stop_requested", "已请求停止采集任务"),
        ("job_deleted", "已删除采集任务"),
        ("misfire", "错过计划已合并执行"),
        ("pipeline_stage_failed", "后处理失败"),
        ("werss_catalog_sync_changed", "WeRSS 公众号清单已同步"),
        ("something_new", "未分类事件"),
    ],
)
def test_event_view_maps_known_and_unknown_summaries(
    tmp_path: Path, event_type: str, summary: str
) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(1, 7, 11, 13, PipelineType.GROUP, "w-1", "info",
        event_type, "collect", "safe", "{}", "worker", "actor", NOW)

    view = service.to_event_view(event)

    assert view.summary == summary
    assert view.subject == "任务 #7 · 运行 #11 · 目标 #13"


@pytest.mark.parametrize(("level", "text"), [("warning", "WARN"), ("error", "ERROR")])
def test_event_view_preserves_alert_level_in_summary(
    tmp_path: Path, level: str, text: str
) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(1, None, None, None, None, None, level,
        "pipeline_stage_failed", None, "safe", "{}", "worker", "actor", NOW)

    view = service.to_event_view(event)

    assert text in view.summary
    assert view.subject == "系统事件"


@pytest.mark.parametrize(
    ("event_type", "level", "target", "summary"),
    [
        (
            "werss_authorization_test_succeeded", "info", "werss",
            "WeRSS 管理凭据测试成功",
        ),
        (
            "werss_authorization_test_succeeded", "info", "email",
            "授权提醒测试邮件发送成功",
        ),
        (
            "werss_authorization_test_failed", "warning", "werss",
            "WARN · WeRSS 管理凭据测试失败",
        ),
        (
            "werss_authorization_test_failed", "warning", "email",
            "WARN · 授权提醒测试邮件发送失败",
        ),
        (
            "werss_authorization_test_succeeded", "info", "unknown",
            "授权提醒连接测试成功",
        ),
    ],
)
def test_authorization_test_event_summary_distinguishes_target(
    tmp_path: Path, event_type: str, level: str, target: str, summary: str,
) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(
        1, None, None, None, None, None, level, event_type, None, "safe",
        json.dumps({"target": target}), "admin", "admin", NOW,
    )

    assert service.to_event_view(event).summary == summary


def test_misfire_event_shows_missed_schedule_count(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(
        1, 10, 757, None, PipelineType.ARTICLE, "w-1", "warning",
        "misfire", None, "safe", '{"missed_count":75}', "worker", "actor", NOW,
    )

    view = service.to_event_view(event)

    assert view.summary == "WARN · 错过计划已合并执行"
    assert [(item.label, item.value) for item in view.metric_items] == [
        ("错过计划", "75")
    ]


def test_run_level_event_shows_target_count_and_names(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(
        1, 10, 757, None, PipelineType.ARTICLE, "w-1", "warning",
        "misfire", None, "safe", "{}", "worker", "actor", NOW,
        target_count=2,
        target_names=("成都鸡蛋价格", "贵阳鸡蛋价格"),
    )

    view = service.to_event_view(event)

    assert view.subject == "公众号 · 本轮 2 个目标"
    assert view.event.target_names == ("成都鸡蛋价格", "贵阳鸡蛋价格")


def test_single_target_run_level_event_shows_specific_name(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(
        1, 10, 757, None, PipelineType.ARTICLE, "w-1", "info",
        "collection_run_finished", None, "safe", "{}", "worker", "actor", NOW,
        target_count=1,
        target_names=("成都鸡蛋价格",),
    )

    assert service.to_event_view(event).subject == "公众号 · 成都鸡蛋价格"


def test_event_view_whitelists_ordered_scalar_metrics(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    metrics = json.dumps({
        "target_total_count": 9, "executed_target_count": 8,
        "target_success_count": 7, "target_failed_count": -1, "failed_count": 2,
        "insert_count": 1.5, "duplicate_count": True, "skipped_count": "3",
        "read_count": float("nan"), "unknown": {"secret": 1},
    })
    event = RuntimeEvent(1, None, None, None, None, None, "info",
        "collection_run_finished", None, "safe", metrics, "worker", "actor", NOW)

    view = service.to_event_view(event)

    assert [(item.label, item.value) for item in view.metric_items] == [
        ("目标", "8"), ("成功", "7"), ("失败", "2"),
        ("新增", "1.5"), ("重复", "true"),
    ]
    assert "unknown" in view.technical_metrics


def test_event_view_handles_unavailable_metrics(tmp_path: Path) -> None:
    service = RuntimeMonitorService(Repo(), tmp_path, heartbeat_ttl_seconds=30)
    event = RuntimeEvent(1, None, None, None, None, None, "info",
        "collection_run_started", None, "safe", "指标无效", "worker", "actor", NOW)

    view = service.to_event_view(event)

    assert view.metric_items == ()
    assert view.technical_metrics == "指标不可用"
