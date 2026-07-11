from __future__ import annotations

import json
import builtins
import signal
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.domain.collection_jobs import PipelineType, RunStatus
from app.core.config import load_config
from app.pipelines.article_polling_runner import (
    ArticlePollingRunResult,
    ArticlePollingTarget,
)
from app.pipelines.group_polling_runner import (
    GroupPollingRunResult,
    GroupPollingTarget,
)
from app.storage.collection_runtime_repo import (
    ClaimedCollectionRun,
    ClaimedTarget,
)
from app.workers.collector_worker import (
    CollectorTickResult,
    ManagedCollectorWorker,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 30, tzinfo=ZONE)


def group_snapshot(**changes) -> str:
    values = {
        "poll_interval_seconds": 30,
        "backtrack_pages": 4,
        "extra_backtrack_pages": 8,
        "is_core_group": True,
        "remark": None,
    }
    values.update(changes)
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def article_snapshot(**changes) -> str:
    values = {
        "account_type": "subscription",
        "feed_url": "http://127.0.0.1:8001/feed/industry.xml",
        "source_type": "rss",
        "request_timeout_seconds": 30,
        "poll_interval_minutes": 10,
        "daily_window_start": "07:30:00",
        "daily_window_end": "19:30:00",
        "max_articles_per_round": 5,
        "collect_today_only": True,
        "dedup_key": "article_hash",
        "remark": None,
    }
    values.update(changes)
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def target(
    target_id: int,
    *,
    source_id: int | None = None,
    name: str | None = None,
    priority: int = 1,
    snapshot: str | None = None,
) -> ClaimedTarget:
    return ClaimedTarget(
        job_target_id=target_id,
        source_id=source_id or target_id,
        source_name=name or f"目标{target_id}",
        priority=priority,
        config_snapshot_json=snapshot or group_snapshot(),
    )


def claimed_run(
    pipeline: PipelineType = PipelineType.GROUP,
    targets: tuple[ClaimedTarget, ...] | None = None,
) -> ClaimedCollectionRun:
    if targets is None:
        targets = (
            target(
                101,
                name="核心群" if pipeline is PipelineType.GROUP else "行业观察",
                snapshot=(
                    group_snapshot()
                    if pipeline is PipelineType.GROUP
                    else article_snapshot()
                ),
            ),
        )
    return ClaimedCollectionRun(
        run_id=41,
        job_id=7,
        job_name="托管采集",
        pipeline_type=pipeline,
        scheduled_at=NOW,
        status=RunStatus.RUNNING,
        targets=targets,
    )


class RuntimeRepo:
    def __init__(self, run=None) -> None:
        self.run = run
        self.claim_calls = []
        self.start_calls = []
        self.finish_target_calls = []
        self.finish_run_calls = []
        self.cancel_calls = []
        self.stop_results = []
        self.heartbeat_calls = []
        self.heartbeat_result = True
        self.abort_calls = []
        self.claim_error = None
        self.stop_error = None
        self.start_error = None
        self.finish_target_error = None
        self.finish_run_error = None

    def claim_next_due(self, now, worker_id, lease_seconds, pipeline_types=None):
        self.claim_calls.append((now, worker_id, lease_seconds, pipeline_types))
        if self.claim_error is not None:
            raise self.claim_error
        result, self.run = self.run, None
        return result

    def is_stop_requested(self, job_id):
        if self.stop_results:
            return self.stop_results.pop(0)
        if self.stop_error is not None:
            raise self.stop_error
        return False

    def start_target(self, run_id, job_target_id, batch_id, now):
        self.start_calls.append((run_id, job_target_id, batch_id, now))
        if self.start_error is not None:
            raise self.start_error
        return 500 + job_target_id

    def finish_target(self, target_run_id, outcome, now):
        self.finish_target_calls.append((target_run_id, outcome, now))
        if self.finish_target_error is not None:
            raise self.finish_target_error

    def cancel_queued_targets(self, run_id, now):
        self.cancel_calls.append((run_id, now))
        return 1

    def finish_run(self, run_id, status, now):
        self.finish_run_calls.append((run_id, status, now))
        if self.finish_run_error is not None:
            raise self.finish_run_error

    def heartbeat_run(self, run_id, worker_id, now, lease_seconds):
        self.heartbeat_calls.append((run_id, worker_id, now, lease_seconds))
        if isinstance(self.heartbeat_result, BaseException):
            raise self.heartbeat_result
        return self.heartbeat_result

    def abort_expired_runs(self, now):
        self.abort_calls.append(now)
        return 0


class RaceRuntimeRepo(RuntimeRepo):
    def __init__(self) -> None:
        super().__init__()
        self.heartbeat_entered = threading.Event()
        self.heartbeat_release = threading.Event()
        self.raise_after_release = None

    def heartbeat_run(self, run_id, worker_id, now, lease_seconds):
        self.heartbeat_calls.append((run_id, worker_id, now, lease_seconds))
        self.heartbeat_entered.set()
        assert self.heartbeat_release.wait(5)
        if self.raise_after_release is not None:
            raise self.raise_after_release
        return False


class HealthMonitor:
    def __init__(self, can_collect=True) -> None:
        self.can_collect_result = can_collect
        self.can_collect_calls = []
        self.check_calls = []

    def can_collect(self, now):
        self.can_collect_calls.append(now)
        return self.can_collect_result

    def run_check(self, now):
        self.check_calls.append(now)
        return object()


class HeartbeatRepo:
    def __init__(self, register_result=True) -> None:
        self.records = []
        self.register_result = register_result
        self.register_calls = []
        self.upsert_error = None

    def upsert_heartbeat(self, record):
        if self.upsert_error is not None:
            raise self.upsert_error
        self.records.append(record)

    def register_collector_start(self, record, now, ttl_seconds):
        self.register_calls.append((record, now, ttl_seconds))
        return self.register_result


class BlockingHeartbeatRepo(HeartbeatRepo):
    def __init__(self) -> None:
        super().__init__()
        self.running_write_entered = threading.Event()
        self.running_write_release = threading.Event()

    def upsert_heartbeat(self, record):
        if record.status == "running" and not self.running_write_entered.is_set():
            self.running_write_entered.set()
            assert self.running_write_release.wait(5)
        super().upsert_heartbeat(record)


class EventRepo:
    def __init__(self, error_on_type=None) -> None:
        self.events = []
        self.error_on_type = error_on_type

    def append_event(self, event):
        if event.event_type == self.error_on_type:
            raise RuntimeError("event database temporarily unavailable")
        self.events.append(event)
        return len(self.events)


class Runner:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def run_once(self, now):
        self.calls.append((now, threading.get_ident()))
        if self.error is not None:
            raise self.error
        return self.result


class BlockingRunner(Runner):
    def __init__(self, result) -> None:
        super().__init__(result=result)
        self.started = threading.Event()
        self.release = threading.Event()

    def run_once(self, now):
        self.calls.append((now, threading.get_ident()))
        self.started.set()
        assert self.release.wait(5)
        return self.result


class StopCheckBlockingArticleRunner(Runner):
    def __init__(self, stop_provider) -> None:
        super().__init__()
        self.stop_provider = stop_provider
        self.checked = threading.Event()
        self.release = threading.Event()

    def run_once(self, now):
        assert self.stop_provider() is True
        self.checked.set()
        assert self.release.wait(5)
        return ArticlePollingRunResult(
            1,
            0,
            0,
            0,
            interrupted_count=1,
            stop_requested_count=1,
            error_code="ARTICLE_STOP_REQUESTED",
        )


class Factories:
    def __init__(self) -> None:
        self.group_result = GroupPollingRunResult(1, 1, 0, 0, 2, 1, 1)
        self.article_result = ArticlePollingRunResult(
            1, 1, 0, 0, link_count=2, raw_insert_count=1,
            duplicate_count=1,
        )
        self.group_calls = []
        self.article_calls = []
        self.group_runner = None
        self.article_runner = None
        self.group_error = None
        self.article_error = None

    def group(self, polling_target, batch_id):
        self.group_calls.append((polling_target, batch_id))
        if self.group_error is not None:
            raise self.group_error
        return self.group_runner or Runner(self.group_result)

    def article(self, polling_target, batch_id, stop_provider):
        self.article_calls.append((polling_target, batch_id, stop_provider))
        if self.article_error is not None:
            raise self.article_error
        return self.article_runner or Runner(self.article_result)


def build_worker(
    *,
    runtime=None,
    health=None,
    heartbeat=None,
    events=None,
    factories=None,
    now_provider=lambda: NOW,
    auto_register=True,
    article_max_concurrency=1,
):
    runtime = runtime or RuntimeRepo()
    health = health or HealthMonitor()
    heartbeat = heartbeat or HeartbeatRepo()
    events = events or EventRepo()
    factories = factories or Factories()
    worker = ManagedCollectorWorker(
        runtime_repo=runtime,
        event_repo=events,
        heartbeat_repo=heartbeat,
        health_monitor=health,
        group_runner_factory=factories.group,
        article_runner_factory=factories.article,
        worker_id="collector-host-a-123",
        hostname="HOST-A",
        process_id=123,
        version="1.0.0",
        start_time=NOW - timedelta(minutes=5),
        run_lease_seconds=120,
        article_max_concurrency=article_max_concurrency,
        batch_id_factory=lambda run, item: f"{run.pipeline_type.value}-{run.run_id}-{item.job_target_id}",
        now_provider=now_provider,
    )
    if auto_register:
        assert worker.register_start(NOW, 30) is True
    return worker, runtime, health, heartbeat, events, factories


def test_article_targets_execute_concurrently_with_distinct_batches_and_bounded_cap() -> None:
    lock = threading.Lock(); active = 0; peak = 0
    class BlockingRunner:
        def run_once(self, now):
            nonlocal active, peak
            with lock: active += 1; peak = max(peak, active)
            threading.Event().wait(0.04)
            with lock: active -= 1
            return ArticlePollingRunResult(1, 1, 0, 0, raw_insert_count=1)
    factories = Factories()
    factories.article = lambda target, batch_id, stop: (
        factories.article_calls.append((target, batch_id, stop)) or BlockingRunner()
    )
    targets = tuple(target(i, name=f"账号{i}", snapshot=article_snapshot()) for i in range(1, 6))
    runtime = RuntimeRepo(claimed_run(PipelineType.ARTICLE, targets))
    worker, *_ = build_worker(
        runtime=runtime, factories=factories, article_max_concurrency=2
    )
    result = worker.run_tick(NOW)
    assert result.executed_target_count == 5
    assert 1 < peak <= 2
    batches = [call[1] for call in factories.article_calls]
    assert len(set(batches)) == 5
    assert len(runtime.finish_target_calls) == 5
    assert runtime.finish_run_calls[-1][1] is RunStatus.SUCCESS


def test_wechat_unhealthy_blocks_group_but_not_article() -> None:
    worker, runtime, health, _, events, _ = build_worker(
        health=HealthMonitor(False)
    )
    assert worker.can_claim(PipelineType.GROUP, NOW) is False
    assert worker.can_claim(PipelineType.ARTICLE, NOW) is True
    assert health.can_collect_calls == [NOW]


def test_unhealthy_wechat_claims_only_article_without_group_lease() -> None:
    runtime = RuntimeRepo(claimed_run(PipelineType.ARTICLE))
    worker, _, health, _, _, factories = build_worker(
        runtime=runtime, health=HealthMonitor(False)
    )
    result = worker.run_tick(NOW)
    assert result.pipeline_type is PipelineType.ARTICLE
    assert runtime.claim_calls == [(NOW, worker.worker_id, 120, (PipelineType.ARTICLE,))]
    assert health.can_collect_calls == [NOW]
    assert len(factories.article_calls) == 1


def test_unhealthy_wechat_leaves_group_due_work_unclaimed() -> None:
    runtime = RuntimeRepo(None)
    worker, _, health, _, events, _ = build_worker(
        runtime=runtime, health=HealthMonitor(False)
    )
    result = worker.run_tick(NOW)
    assert result.status == "idle"
    assert runtime.claim_calls == [(NOW, worker.worker_id, 120, (PipelineType.ARTICLE,))]
    assert runtime.finish_run_calls == []
    assert events.events == []


def test_healthy_idle_tick_claims_at_most_once_without_log_flood() -> None:
    worker, runtime, _, _, events, _ = build_worker()
    first = worker.run_tick(NOW)
    second = worker.run_tick(NOW + timedelta(seconds=5))
    assert first.status == second.status == "idle"
    assert len(runtime.claim_calls) == 2
    assert events.events == []


@pytest.mark.parametrize(
    ("fault", "runner_call_count"),
    [
        ("claimed_event", 0),
        ("start_target", 0),
        ("finish_target", 1),
        ("finish_run", 1),
    ],
)
def test_claimed_run_repo_or_event_failure_degrades_without_retrying_rpa(
    fault, runner_call_count
) -> None:
    runtime = RuntimeRepo(claimed_run())
    events = EventRepo(
        error_on_type=(
            "collection_run_claimed" if fault == "claimed_event" else None
        )
    )
    factories = Factories()
    runner = Runner(factories.group_result)
    factories.group_runner = runner
    if fault == "start_target":
        runtime.start_error = RuntimeError("start target unavailable")
    elif fault == "finish_target":
        runtime.finish_target_error = RuntimeError("finish target unavailable")
    elif fault == "finish_run":
        runtime.finish_run_error = RuntimeError("finish run unavailable")
    worker, _, _, _, _, _ = build_worker(
        runtime=runtime,
        events=events,
        factories=factories,
    )

    result = worker.run_tick(NOW)
    second = worker.run_tick(NOW + timedelta(seconds=5))

    assert result.status == "degraded"
    assert result.run_id == 41
    assert result.pipeline_type is PipelineType.GROUP
    assert second.status == "degraded"
    assert len(runtime.claim_calls) == 1
    assert len(runner.calls) == runner_call_count
    assert len(runtime.finish_target_calls) == (
        1 if fault in {"finish_target", "finish_run"} else 0
    )
    assert len(runtime.finish_run_calls) == (1 if fault == "finish_run" else 0)

    assert worker.recover_expired_now() == 0
    assert runtime.abort_calls == [NOW]


def test_execute_run_uses_snapshot_and_stable_target_order() -> None:
    targets = (
        target(102, name="乙群", priority=2, snapshot=group_snapshot(backtrack_pages=99)),
        target(101, name="甲群", priority=1, snapshot=group_snapshot(backtrack_pages=7)),
    )
    run = claimed_run(targets=targets)
    factories = Factories()
    worker, runtime, _, _, _, _ = build_worker(
        runtime=RuntimeRepo(run), factories=factories
    )

    result = worker.run_tick(NOW)

    assert result.status == "success"
    assert result.pipeline_type is PipelineType.GROUP
    assert result.executed_target_count == 2
    assert [call[0].group_name for call in factories.group_calls] == ["甲群", "乙群"]
    assert [call[0].poll_interval_seconds for call in factories.group_calls] == [30, 30]
    assert [call[1] for call in factories.group_calls] == ["group-41-101", "group-41-102"]
    assert [call[1] for call in runtime.start_calls] == [101, 102]
    assert runtime.finish_run_calls == [(41, RunStatus.SUCCESS, NOW)]
    target_events = [
        event for event in worker.event_repo.events
        if event.event_type in {"collection_target_started", "collection_target_finished"}
    ]
    assert [event.event_type for event in target_events] == [
        "collection_target_started",
        "collection_target_finished",
        "collection_target_started",
        "collection_target_finished",
    ]
    assert [event.target_run_id for event in target_events] == [601, 601, 602, 602]
    assert all("甲群" not in event.message and "乙群" not in event.message for event in target_events)


def test_stop_between_group_targets_cancels_remaining() -> None:
    run = claimed_run(
        targets=(target(101, name="甲群"), target(102, name="乙群", priority=2))
    )
    runtime = RuntimeRepo()
    runtime.stop_results = [False, True]
    worker, _, _, _, _, _ = build_worker(runtime=runtime)

    result = worker.execute_run(run, NOW)

    assert result.executed_target_count == 1
    assert result.status == "cancelled"
    assert len(runtime.finish_target_calls) == 1
    assert runtime.cancel_calls == [(41, NOW)]
    assert runtime.finish_run_calls == [(41, RunStatus.CANCELLED, NOW)]


@pytest.mark.parametrize(
    "snapshot",
    [
        "[]",
        group_snapshot(poll_interval_seconds=True),
        group_snapshot(unknown_field="unsafe"),
        '{"poll_interval_seconds":30}',
        "not-json",
    ],
)
def test_invalid_snapshot_fails_target_without_constructing_runner(snapshot) -> None:
    run = claimed_run(targets=(target(101, snapshot=snapshot),))
    worker, runtime, _, _, _, factories = build_worker()

    result = worker.execute_run(run, NOW)

    assert result.status == "failed"
    assert factories.group_calls == []
    assert len(runtime.start_calls) == 1
    outcome = runtime.finish_target_calls[0][1]
    assert outcome.status == "failed"
    assert outcome.error_code == "INVALID_TARGET_SNAPSHOT"
    assert "not-json" not in (outcome.error_summary or "")
    assert runtime.finish_run_calls == [(41, RunStatus.FAILED, NOW)]


@pytest.mark.parametrize(
    ("pipeline", "runner_result", "expected_status", "counts"),
    [
        (
            PipelineType.GROUP,
            GroupPollingRunResult(1, 1, 0, 0, 5, 2, 3),
            "success",
            (5, 2, 3, 0),
        ),
        (
            PipelineType.GROUP,
            GroupPollingRunResult(
                1, 0, 0, 1, error_code="WECHAT_UI_LOCK_TIMEOUT",
                error_summary="busy",
            ),
            "failed",
            (0, 0, 0, 0),
        ),
        (
            PipelineType.ARTICLE,
            ArticlePollingRunResult(
                1, 0, 0, 0, skipped_count=1,
                error_code="WECHAT_ARTICLE_NO_TODAY_ARTICLE",
            ),
            "success",
            (0, 0, 0, 1),
        ),
        (
            PipelineType.ARTICLE,
            ArticlePollingRunResult(
                1, 0, 0, 0, interrupted_count=1,
                core_group_interrupted_count=1,
                error_code="ARTICLE_INTERRUPTED_FOR_CORE_GROUP",
            ),
            "success",
            (0, 0, 0, 1),
        ),
    ],
)
def test_runner_results_map_to_target_outcomes(
    pipeline, runner_result, expected_status, counts
) -> None:
    factories = Factories()
    if pipeline is PipelineType.GROUP:
        factories.group_result = runner_result
    else:
        factories.article_result = runner_result
    run = claimed_run(pipeline)
    worker, runtime, _, _, _, _ = build_worker(factories=factories)

    result = worker.execute_run(run, NOW)

    assert result.status == expected_status
    outcome = runtime.finish_target_calls[0][1]
    assert (
        outcome.read_count,
        outcome.insert_count,
        outcome.duplicate_count,
        outcome.skipped_count,
    ) == counts


def test_article_job_stop_cancels_current_and_remaining_targets() -> None:
    run = claimed_run(
        PipelineType.ARTICLE,
        targets=(
            target(101, name="甲号", snapshot=article_snapshot()),
            target(102, name="乙号", priority=2, snapshot=article_snapshot()),
        ),
    )
    factories = Factories()
    factories.article_result = ArticlePollingRunResult(
        1, 0, 0, 0, interrupted_count=1, stop_requested_count=1,
        error_code="ARTICLE_STOP_REQUESTED",
    )
    worker, runtime, _, _, _, _ = build_worker(factories=factories)

    result = worker.execute_run(run, NOW)

    assert result.status == "cancelled"
    assert result.executed_target_count == 1
    assert runtime.finish_target_calls[0][1].status == "cancelled"
    assert runtime.cancel_calls == [(41, NOW)]
    assert runtime.finish_run_calls == [(41, RunStatus.CANCELLED, NOW)]


def test_mixed_success_and_failure_finishes_partial_success() -> None:
    run = claimed_run(
        targets=(target(101, name="甲群"), target(102, name="乙群", priority=2))
    )
    factories = Factories()
    calls = 0

    def group_factory(polling_target, batch_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Runner(GroupPollingRunResult(1, 1, 0, 0, 1, 1, 0))
        return Runner(
            GroupPollingRunResult(
                1, 0, 1, 0, error_code="WECHAT_RPA_ERROR",
                error_summary="failed",
            )
        )

    factories.group = group_factory
    worker, runtime, _, _, _, _ = build_worker(factories=factories)

    result = worker.execute_run(run, NOW)

    assert result.status == "partial_success"
    assert runtime.finish_run_calls == [
        (41, RunStatus.PARTIAL_SUCCESS, NOW)
    ]


def test_runner_build_error_is_failed_and_sanitized() -> None:
    factories = Factories()
    factories.group_error = RuntimeError(
        "<b>13812345678</b> https://mp.weixin.qq.com/s/raw"
    )
    worker, runtime, _, _, _, _ = build_worker(factories=factories)

    result = worker.execute_run(claimed_run(), NOW)

    assert result.status == "failed"
    outcome = runtime.finish_target_calls[0][1]
    assert outcome.error_code == "RUNNER_BUILD_ERROR"
    assert "13812345678" not in outcome.error_summary
    assert "https://" not in outcome.error_summary
    assert "<" not in outcome.error_summary


def test_invalid_runner_result_is_finished_failed_not_left_running() -> None:
    factories = Factories()
    factories.group_runner = Runner(object())
    worker, runtime, _, _, _, _ = build_worker(factories=factories)

    result = worker.execute_run(claimed_run(), NOW)

    assert result.status == "failed"
    assert len(runtime.finish_target_calls) == 1
    outcome = runtime.finish_target_calls[0][1]
    assert outcome.status == "failed"
    assert outcome.error_code == "RUNNER_RESULT_ERROR"
    assert runtime.finish_run_calls == [(41, RunStatus.FAILED, NOW)]


def test_heartbeat_refreshes_thread_safe_active_run_and_clears_after_finish() -> None:
    blocking = BlockingRunner(GroupPollingRunResult(1, 1, 0, 0, 1, 1, 0))
    factories = Factories()
    factories.group_runner = blocking
    worker, runtime, _, heartbeat, _, _ = build_worker(factories=factories)
    errors = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors, lambda: worker.execute_run(claimed_run(), NOW)
        )
    )
    thread.start()
    assert blocking.started.wait(5)

    heartbeat_at = NOW + timedelta(seconds=10)
    worker.heartbeat(heartbeat_at)

    assert runtime.heartbeat_calls == [
        (41, "collector-host-a-123", heartbeat_at, 120)
    ]
    assert heartbeat.records[-1].status == "running"
    blocking.release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert errors == []

    worker.heartbeat(NOW + timedelta(seconds=20))
    assert len(runtime.heartbeat_calls) == 1


def test_shutdown_serializes_heartbeat_writes_in_lifecycle_order() -> None:
    heartbeat = BlockingHeartbeatRepo()
    worker, _, _, _, _, _ = build_worker(heartbeat=heartbeat)
    heartbeat_errors = []
    lifecycle_errors = []

    heartbeat_thread = threading.Thread(
        target=lambda: _capture_error(
            heartbeat_errors,
            lambda: worker.heartbeat(NOW + timedelta(seconds=10)),
        )
    )
    heartbeat_thread.start()
    assert heartbeat.running_write_entered.wait(5)

    def stop_lifecycle() -> None:
        worker.mark_stopping(NOW + timedelta(seconds=11))
        worker.mark_stopped(NOW + timedelta(seconds=12))

    lifecycle_thread = threading.Thread(
        target=lambda: _capture_error(lifecycle_errors, stop_lifecycle)
    )
    lifecycle_thread.start()
    assert lifecycle_thread.is_alive()

    heartbeat.running_write_release.set()
    heartbeat_thread.join(5)
    lifecycle_thread.join(5)

    assert not heartbeat_thread.is_alive()
    assert not lifecycle_thread.is_alive()
    assert heartbeat_errors == lifecycle_errors == []
    assert [record.status for record in heartbeat.records] == [
        "running",
        "stopping",
        "stopped",
    ]


def _capture_error(errors, operation) -> None:
    try:
        operation()
    except Exception as exc:  # pragma: no cover - assertion reports content
        errors.append(exc)


def test_lost_active_lease_marks_degraded_and_stops_future_claims() -> None:
    blocking = BlockingRunner(GroupPollingRunResult(1, 1, 0, 0, 1, 1, 0))
    factories = Factories()
    factories.group_runner = blocking
    worker, runtime, _, heartbeat, _, _ = build_worker(factories=factories)
    runtime.heartbeat_result = False
    errors = []
    thread = threading.Thread(
        target=lambda: _capture_error(
            errors, lambda: worker.execute_run(claimed_run(), NOW)
        )
    )
    thread.start()
    assert blocking.started.wait(5)

    worker.heartbeat(NOW + timedelta(seconds=10))
    assert heartbeat.records[-1].status == "degraded"
    blocking.release.set()
    thread.join(5)
    assert errors == []

    claims_before = len(runtime.claim_calls)
    result = worker.run_tick(NOW + timedelta(seconds=20))
    assert result.status == "degraded"
    assert len(runtime.claim_calls) == claims_before


def test_late_failed_heartbeat_after_run_clear_does_not_degrade_idle_worker() -> None:
    runtime = RaceRuntimeRepo()
    blocking = BlockingRunner(GroupPollingRunResult(1, 1, 0, 0, 1, 1, 0))
    factories = Factories()
    factories.group_runner = blocking
    worker, _, _, heartbeat, _, _ = build_worker(
        runtime=runtime, factories=factories
    )
    run_errors = []
    heartbeat_errors = []
    run_thread = threading.Thread(
        target=lambda: _capture_error(
            run_errors, lambda: worker.execute_run(claimed_run(), NOW)
        )
    )
    run_thread.start()
    assert blocking.started.wait(5)
    heartbeat_thread = threading.Thread(
        target=lambda: _capture_error(
            heartbeat_errors,
            lambda: worker.heartbeat(NOW + timedelta(seconds=10)),
        )
    )
    heartbeat_thread.start()
    assert runtime.heartbeat_entered.wait(5)

    blocking.release.set()
    run_thread.join(5)
    assert not run_thread.is_alive()
    runtime.heartbeat_release.set()
    heartbeat_thread.join(5)
    assert not heartbeat_thread.is_alive()
    assert run_errors == heartbeat_errors == []
    assert heartbeat.records[-1].status == "running"
    assert worker.run_tick(NOW + timedelta(seconds=20)).status == "idle"


def test_late_heartbeat_exception_after_run_clear_does_not_degrade() -> None:
    runtime = RaceRuntimeRepo()
    runtime.raise_after_release = RuntimeError("late db result")
    blocking = BlockingRunner(GroupPollingRunResult(1, 1, 0, 0, 1, 1, 0))
    factories = Factories()
    factories.group_runner = blocking
    worker, _, _, heartbeat, _, _ = build_worker(
        runtime=runtime, factories=factories
    )
    run_errors = []
    heartbeat_errors = []
    run_thread = threading.Thread(
        target=lambda: _capture_error(
            run_errors, lambda: worker.execute_run(claimed_run(), NOW)
        )
    )
    run_thread.start()
    assert blocking.started.wait(5)
    heartbeat_thread = threading.Thread(
        target=lambda: _capture_error(
            heartbeat_errors,
            lambda: worker.heartbeat(NOW + timedelta(seconds=10)),
        )
    )
    heartbeat_thread.start()
    assert runtime.heartbeat_entered.wait(5)
    blocking.release.set()
    run_thread.join(5)
    runtime.heartbeat_release.set()
    heartbeat_thread.join(5)

    assert run_errors == heartbeat_errors == []
    assert heartbeat.records[-1].status == "running"
    assert worker.run_tick(NOW + timedelta(seconds=20)).status == "idle"


def test_transient_claim_failure_recovers_after_successful_idle_heartbeat() -> None:
    runtime = RuntimeRepo()
    runtime.claim_error = RuntimeError("db temporarily unavailable")
    worker, _, _, heartbeat, _, _ = build_worker(runtime=runtime)

    assert worker.run_tick(NOW).status == "degraded"
    runtime.claim_error = None
    worker.heartbeat(NOW + timedelta(seconds=10))

    assert heartbeat.records[-1].status == "running"
    assert worker.status == "running"
    assert worker.run_tick(NOW + timedelta(seconds=20)).status == "idle"


def test_heartbeat_upsert_failure_marks_degraded_then_recovers() -> None:
    heartbeat = HeartbeatRepo()
    worker, _, _, _, _, _ = build_worker(heartbeat=heartbeat)
    heartbeat.upsert_error = RuntimeError("heartbeat database down")

    with pytest.raises(RuntimeError, match="heartbeat database"):
        worker.heartbeat(NOW + timedelta(seconds=10))
    assert worker.run_tick(NOW + timedelta(seconds=11)).status == "degraded"

    heartbeat.upsert_error = None
    worker.heartbeat(NOW + timedelta(seconds=20))
    assert heartbeat.records[-1].status == "running"
    assert worker.status == "running"


def test_successful_lease_heartbeat_does_not_clear_degraded_active_run() -> None:
    runtime = RuntimeRepo()
    runtime.stop_results = [False]
    runtime.stop_error = RuntimeError("stop database unavailable")
    factories = Factories()
    holder = {}
    factory_called = threading.Event()

    def article_factory(target, batch_id, stop_provider):
        runner = StopCheckBlockingArticleRunner(stop_provider)
        holder["runner"] = runner
        factory_called.set()
        return runner

    factories.article = article_factory
    worker, _, _, heartbeat, _, _ = build_worker(
        runtime=runtime, factories=factories
    )
    errors = []
    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: worker.execute_run(
                claimed_run(PipelineType.ARTICLE), NOW
            ),
        )
    )
    thread.start()
    assert factory_called.wait(5)
    runner = holder["runner"]
    assert runner.checked.wait(5)

    worker.heartbeat(NOW + timedelta(seconds=10))

    assert heartbeat.records[-1].status == "degraded"
    assert worker.status == "degraded"
    runner.release.set()
    thread.join(5)
    assert errors == []


def test_long_run_uses_fresh_aware_finish_times() -> None:
    times = iter(
        [NOW + timedelta(minutes=1), NOW + timedelta(minutes=2)]
    )
    worker, runtime, _, _, _, _ = build_worker(
        now_provider=lambda: next(times)
    )

    worker.execute_run(claimed_run(), NOW)

    assert runtime.start_calls[0][3] == NOW
    assert runtime.finish_target_calls[0][2] == NOW + timedelta(minutes=1)
    assert runtime.finish_run_calls[0][2] == NOW + timedelta(minutes=2)


def test_atomic_start_registration_failure_prevents_claim() -> None:
    heartbeat = HeartbeatRepo(register_result=False)
    worker, runtime, _, _, _, _ = build_worker(
        heartbeat=heartbeat, auto_register=False
    )
    assert worker.register_start(NOW, 30) is False
    assert worker.run_tick(NOW).status == "not_registered"
    assert runtime.claim_calls == []


def test_background_wrappers_only_touch_db_and_health_not_rpa() -> None:
    times = iter(
        [NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)]
    )
    worker, runtime, health, heartbeat, _, factories = build_worker(
        now_provider=lambda: next(times)
    )
    worker.heartbeat_now()
    worker.health_check_now()
    worker.recover_expired_now()
    assert heartbeat.records[-1].last_heartbeat_at == NOW
    assert health.check_calls == [NOW + timedelta(seconds=1)]
    assert runtime.abort_calls == [NOW + timedelta(seconds=2)]
    assert factories.group_calls == factories.article_calls == []


def test_shutdown_status_is_safe_and_prevents_new_claim() -> None:
    worker, runtime, _, heartbeat, _, _ = build_worker()
    worker.request_shutdown()
    assert worker.is_shutdown_requested() is True
    assert worker.run_tick(NOW).status == "stopping"
    assert runtime.claim_calls == []
    worker.mark_stopping(NOW)
    worker.mark_stopped(NOW + timedelta(seconds=1))
    assert [record.status for record in heartbeat.records[-2:]] == [
        "stopping",
        "stopped",
    ]


@pytest.mark.parametrize(
    "invalid_now",
    [
        datetime(2026, 7, 10, 9, 30),
        datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc),
    ],
)
def test_worker_requires_exact_shanghai_zoneinfo(invalid_now) -> None:
    worker, _, _, _, _, _ = build_worker()
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        worker.run_tick(invalid_now)
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        worker.heartbeat(invalid_now)


def test_default_worker_identity_is_bounded_and_unique_for_pid_reuse(
    monkeypatch,
) -> None:
    from app.workers import collector_worker

    hostname = "HOST-" + "长" * 300
    monkeypatch.setattr(collector_worker.socket, "gethostname", lambda: hostname)
    monkeypatch.setattr(collector_worker.os, "getpid", lambda: 123)

    first = collector_worker.default_worker_identity()
    second = collector_worker.default_worker_identity()

    assert first[1:] == second[1:] == (hostname, 123)
    assert first[0] != second[0]
    assert len(first[0]) <= 100
    assert len(second[0]) <= 100


class NoConnectEngine:
    def begin(self):
        raise AssertionError("runtime build must not connect")

    def connect(self):
        raise AssertionError("runtime build must not connect")


def test_fake_runtime_factory_never_imports_or_constructs_real_adapters(
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {
            "app.rpa.wxauto_client",
            "app.rpa.screenshots",
            "pywinauto",
        }:
            raise AssertionError(f"fake mode imported real adapter: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    from app.rpa.fake_clients import FakeGroupRpaClient
    from app.storage.article_config_repo import ArticleAccountConfigRecord
    from app.storage.article_raw_repo import MysqlArticleRawRepo
    from app.storage.group_repo import MysqlGroupConfigRepo, MysqlGroupMessageRepo
    from app.workers.runtime_factory import build_managed_collector_worker

    config = load_config(Path("config/config.dev.yaml"))
    engine = NoConnectEngine()
    worker = build_managed_collector_worker(
        config,
        engine=engine,
        worker_id="collector-test",
        hostname="HOST-A",
        process_id=123,
        now_provider=lambda: NOW,
    )

    group_runner = worker.group_runner_factory(
        GroupPollingTarget("核心群", 1, 30), "group-batch"
    )
    article_runner = worker.article_runner_factory(
        ArticleAccountConfigRecord(
            id=1, account_name="行业观察", account_type="subscription",
            feed_url="http://127.0.0.1:8001/feed.xml",
        ),
        "article-batch",
        lambda: False,
    )
    assert isinstance(group_runner.collect_service.rpa, FakeGroupRpaClient)
    assert isinstance(group_runner.collect_service.repo, MysqlGroupMessageRepo)
    assert isinstance(article_runner.runner.collect_service.raw_repo, MysqlArticleRawRepo)
    assert group_runner.collect_service.repo.engine is engine
    assert article_runner.runner.collect_service.raw_repo.engine is engine
    assert not hasattr(article_runner, "lock_repo")
    assert not hasattr(article_runner, "screenshot_root")
    assert worker.runtime_repo.engine is engine
    assert worker.heartbeat_repo.engine is engine
    assert worker.health_monitor.health_repo.engine is engine
    assert worker.health_monitor.ui_lock_repo.engine is engine
    assert group_runner.screenshot_root.is_absolute()
    assert worker.article_max_concurrency == config.pipelines.article.rss_max_concurrency


@pytest.mark.parametrize(
    ("url", "allowed", "expected"),
    [
        ("https://feeds.example/rss", ("127.0.0.1:8001",), None),
        ("http://127.0.0.1:8001/rss", ("127.0.0.1:8001",), ("127.0.0.1", 8001)),
        ("http://127.0.0.1:9000/rss", ("127.0.0.1:8001",), None),
        ("http://[::1]:8001/rss", ("[::1]:8001",), ("::1", 8001)),
    ],
)
def test_rss_private_exception_requires_exact_normalized_endpoint(url, allowed, expected):
    from app.workers.runtime_factory import _allowed_endpoint_for_target
    assert _allowed_endpoint_for_target(url, allowed) == expected


class FakeWindow:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def exists(self, timeout=0):
        return self._exists


class FakeDesktop:
    def __init__(self, classes) -> None:
        self.classes = set(classes)

    def window(self, *, class_name):
        return FakeWindow(class_name in self.classes)


@pytest.mark.parametrize(
    ("classes", "window_available", "logged_in"),
    [
        ({"mmui::MainWindow"}, True, True),
        ({"WeChatMainWndForPC"}, True, True),
        ({"mmui::LoginWindow"}, True, False),
        ({"WeChatLoginWndForPC"}, True, False),
        (set(), False, False),
    ],
)
def test_real_window_and_login_probes_distinguish_state_without_rpa(
    classes, window_available, logged_in
) -> None:
    from app.workers.runtime_factory import _RealLoginProbe, _RealWindowProbe

    desktop = FakeDesktop(classes)
    window_probe = _RealWindowProbe(desktop_factory=lambda: desktop)
    login_probe = _RealLoginProbe(desktop_factory=lambda: desktop)
    assert window_probe.check() is window_available
    assert login_probe.check() is logged_in


class MainWorker:
    def __init__(self, register_result=True) -> None:
        self.register_result = register_result
        self.calls = []
        self.run_thread_ids = []
        self.stopping_error = None
        self.stopped_error = None

    def register_start(self, now, ttl_seconds):
        self.calls.append(("register", now, ttl_seconds))
        return self.register_result

    def health_check_now(self):
        self.calls.append(("health",))

    def heartbeat(self, now):
        self.calls.append(("heartbeat", now))

    def heartbeat_now(self):
        self.calls.append(("heartbeat_now",))

    def recover_expired_now(self):
        self.calls.append(("recover",))

    def run_tick(self, now):
        self.calls.append(("run", now))
        self.run_thread_ids.append(threading.get_ident())
        return None

    def request_shutdown(self):
        self.calls.append(("request_shutdown",))

    def mark_stopping(self, now):
        self.calls.append(("stopping", now))
        if self.stopping_error is not None:
            raise self.stopping_error

    def mark_stopped(self, now):
        self.calls.append(("stopped", now))
        if self.stopped_error is not None:
            raise self.stopped_error


class Scheduler:
    instances = []

    def __init__(self, *, timezone):
        self.timezone = timezone
        self.jobs = []
        self.started = False
        self.shutdown_wait = None
        self.__class__.instances.append(self)

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))

    def start(self):
        self.started = True

    def shutdown(self, *, wait):
        self.shutdown_wait = wait


def test_collector_main_once_registers_health_before_main_thread_rpa() -> None:
    from app.workers.collector_main import main

    Scheduler.instances.clear()
    worker = MainWorker()
    main_thread = threading.get_ident()
    result = main(
        ["--config", "config/config.dev.yaml", "--once"],
        runtime_builder=lambda config: worker,
        scheduler_factory=Scheduler,
        now_provider=lambda: NOW,
    )

    assert result == 0
    scheduler = Scheduler.instances[-1]
    assert scheduler.timezone == "Asia/Shanghai"
    assert scheduler.started is True
    assert scheduler.shutdown_wait is False
    assert [job[0].__name__ for job in scheduler.jobs] == [
        "heartbeat_now",
        "health_check_now",
        "recover_expired_now",
    ]
    assert all(job[1] == "interval" for job in scheduler.jobs)
    assert [job[2]["seconds"] for job in scheduler.jobs] == [10, 300, 10]
    assert all(job[2]["max_instances"] == 1 for job in scheduler.jobs)
    assert all(job[2]["coalesce"] is True for job in scheduler.jobs)
    names = [call[0] for call in worker.calls]
    assert names.index("register") < names.index("health") < names.index("run")
    assert worker.run_thread_ids == [main_thread]
    assert names[-2:] == ["stopping", "stopped"]


def test_collector_main_keeps_scheduler_running_after_degraded_tick(
    monkeypatch,
) -> None:
    from app.workers import collector_main

    class DegradedThenInterruptWorker(MainWorker):
        def __init__(self) -> None:
            super().__init__()
            self.tick_count = 0
            self.scheduler_was_running = False

        def run_tick(self, now):
            self.calls.append(("run", now))
            self.tick_count += 1
            if self.tick_count == 1:
                return CollectorTickResult(
                    "degraded", 41, PipelineType.GROUP, 0
                )
            scheduler = Scheduler.instances[-1]
            self.scheduler_was_running = (
                scheduler.started and scheduler.shutdown_wait is None
            )
            self.recover_expired_now()
            raise KeyboardInterrupt

    Scheduler.instances.clear()
    monkeypatch.setattr(
        collector_main,
        "_bounded_tick_delay",
        lambda status, failures, base: 0,
    )
    worker = DegradedThenInterruptWorker()

    result = collector_main.main(
        ["--config", "config/config.dev.yaml"],
        runtime_builder=lambda config: worker,
        scheduler_factory=Scheduler,
        now_provider=lambda: NOW,
    )

    assert result == 0
    assert worker.tick_count == 2
    assert worker.scheduler_was_running is True
    assert ("recover",) in worker.calls


def test_collector_main_duplicate_instance_exits_before_health_or_scheduler() -> None:
    from app.workers.collector_main import main

    Scheduler.instances.clear()
    worker = MainWorker(register_result=False)
    result = main(
        ["--config", "config/config.dev.yaml", "--once"],
        runtime_builder=lambda config: worker,
        scheduler_factory=Scheduler,
        now_provider=lambda: NOW,
    )
    assert result == 1
    assert [call[0] for call in worker.calls] == ["register"]
    assert Scheduler.instances == []


def test_collector_main_invalid_mode_exits_two_without_building_runtime(
    tmp_path,
) -> None:
    from app.workers.collector_main import main

    raw = yaml.safe_load(Path("config/config.dev.yaml").read_text(encoding="utf-8"))
    raw["workers"]["collector_mode"] = "unsafe"
    path = tmp_path / "invalid.yaml"
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    builds = []
    result = main(
        ["--config", str(path), "--once"],
        runtime_builder=lambda config: builds.append(config),
        scheduler_factory=Scheduler,
        now_provider=lambda: NOW,
    )
    assert result == 2
    assert builds == []


def test_collector_main_help_has_no_runtime_side_effect() -> None:
    from app.workers.collector_main import main

    builds = []
    with pytest.raises(SystemExit) as exc:
        main(["--help"], runtime_builder=lambda config: builds.append(config))
    assert exc.value.code == 0
    assert builds == []


@pytest.mark.parametrize(
    ("status", "failures", "expected"),
    [
        ("idle", 4, 5),
        ("degraded", 1, 10),
        ("degraded", 2, 20),
        ("degraded", 10, 60),
    ],
)
def test_collector_main_degraded_backoff_is_bounded(
    status, failures, expected
) -> None:
    from app.workers.collector_main import _bounded_tick_delay

    assert _bounded_tick_delay(status, failures, 5) == expected


def test_collector_main_shutdown_heartbeat_failure_still_cleans_up(
    capsys,
) -> None:
    from app.workers.collector_main import main

    Scheduler.instances.clear()
    worker = MainWorker()
    worker.stopping_error = RuntimeError("secret stopping detail")
    worker.stopped_error = RuntimeError("secret stopped detail")
    before = signal.getsignal(signal.SIGINT)

    result = main(
        ["--config", "config/config.dev.yaml", "--once"],
        runtime_builder=lambda config: worker,
        scheduler_factory=Scheduler,
        now_provider=lambda: NOW,
    )

    assert result == 1
    scheduler = Scheduler.instances[-1]
    assert scheduler.shutdown_wait is False
    assert signal.getsignal(signal.SIGINT) == before
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "secret" not in stderr


def test_collector_main_scheduler_start_failure_still_cleans_up(
    capsys,
) -> None:
    from app.workers.collector_main import main

    class StartFailScheduler(Scheduler):
        def start(self):
            raise RuntimeError("secret scheduler detail")

    StartFailScheduler.instances.clear()
    worker = MainWorker()
    before = signal.getsignal(signal.SIGINT)

    result = main(
        ["--config", "config/config.dev.yaml", "--once"],
        runtime_builder=lambda config: worker,
        scheduler_factory=StartFailScheduler,
        now_provider=lambda: NOW,
    )

    assert result == 1
    scheduler = StartFailScheduler.instances[-1]
    assert scheduler.shutdown_wait is False
    assert signal.getsignal(signal.SIGINT) == before
    assert [call[0] for call in worker.calls][-3:] == [
        "request_shutdown",
        "stopping",
        "stopped",
    ]
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "secret" not in stderr
