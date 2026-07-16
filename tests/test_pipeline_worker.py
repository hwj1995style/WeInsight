from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.report_generation_service import ReportExecutionResult
from app.workers import pipeline_main
from app.workers.pipeline_runtime_factory import build_pipeline_worker
from app.workers.pipeline_worker import PipelineWorker


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 11, 0, 10, tzinfo=ZONE)


@dataclass(frozen=True)
class StageResult:
    success_count: int


class StageService:
    def __init__(self, name: str, order: list[str], *, error: Exception | None = None):
        self.name = name
        self.order = order
        self.error = error
        self.calls: list[tuple[int, datetime]] = []

    def _run(self, limit: int, now: datetime) -> StageResult:
        self.order.append(self.name)
        self.calls.append((limit, now))
        if self.error is not None:
            raise self.error
        return StageResult(success_count={
            "group_clean": 3,
            "group_analysis": 4,
            "article_parse": 5,
            "article_analysis": 2,
        }[self.name])

    def clean_once(self, limit: int, clean_time: datetime) -> StageResult:
        return self._run(limit, clean_time)

    def analyze_once(self, limit: int, analyze_time: datetime) -> StageResult:
        return self._run(limit, analyze_time)

    def parse_once(self, limit: int, parse_time: datetime) -> StageResult:
        return self._run(limit, parse_time)


class ReportRepo:
    def __init__(self, requests=None, *, error: Exception | None = None) -> None:
        self.requests = list(requests or [])
        self.error = error
        self.calls: list[tuple[datetime, str, int]] = []

    def claim_next(self, now, worker_id, lease_seconds):
        self.calls.append((now, worker_id, lease_seconds))
        if self.error is not None:
            raise self.error
        return self.requests.pop(0) if self.requests else None


class ReportService:
    def __init__(
        self,
        *,
        status: str = "partial_success",
        error: Exception | None = None,
        compensation_error: Exception | None = None,
    ):
        self.status = status
        self.error = error
        self.compensation_error = compensation_error
        self.execute_calls = []
        self.compensation_calls: list[tuple[date, datetime]] = []

    def execute_request(self, request, worker_id, now):
        self.execute_calls.append((request, worker_id, now))
        if self.error is not None:
            raise self.error
        return ReportExecutionResult(self.status, 2, 1, "safe")

    def ensure_compensation_request(self, report_date, now):
        self.compensation_calls.append((report_date, now))
        if self.compensation_error is not None:
            raise self.compensation_error
        return 73


class EventRepo:
    def __init__(self, *, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def append_event(self, event):
        self.events.append(event)
        if self.fail:
            raise RuntimeError("event db unavailable")
        return len(self.events)


class HeartbeatRepo:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.records = []
        self.error = error

    def upsert_heartbeat(self, record):
        self.records.append(record)
        if self.error is not None:
            raise self.error


def worker_fixture(
    *,
    stage_errors: dict[str, Exception] | None = None,
    report_requests=None,
    report_repo_error: Exception | None = None,
    report_service_error: Exception | None = None,
    compensation_error: Exception | None = None,
    heartbeat_error: Exception | None = None,
    event_fail: bool = False,
    now_provider=lambda: NOW,
):
    order: list[str] = []
    errors = stage_errors or {}
    stages = {
        name: StageService(name, order, error=errors.get(name))
        for name in (
            "group_clean",
            "group_analysis",
            "article_parse",
            "article_analysis",
        )
    }
    report_repo = ReportRepo(report_requests, error=report_repo_error)
    report_service = ReportService(
        error=report_service_error,
        compensation_error=compensation_error,
    )
    event_repo = EventRepo(fail=event_fail)
    heartbeat_repo = HeartbeatRepo(error=heartbeat_error)
    worker = PipelineWorker(
        group_clean_service=stages["group_clean"],
        group_analysis_service=stages["group_analysis"],
        article_parse_service=stages["article_parse"],
        article_analysis_service=stages["article_analysis"],
        report_repo=report_repo,
        report_service=report_service,
        event_repo=event_repo,
        heartbeat_repo=heartbeat_repo,
        worker_id="pipeline-test-1",
        hostname="test-host",
        process_id=1234,
        version="pipeline-v1",
        start_time=NOW,
        report_lease_seconds=120,
        group_clean_batch_size=50,
        group_analysis_batch_size=100,
        article_parse_batch_size=20,
        article_analysis_batch_size=20,
        now_provider=now_provider,
    )
    return SimpleNamespace(
        worker=worker,
        order=order,
        stages=stages,
        report_repo=report_repo,
        report_service=report_service,
        event_repo=event_repo,
        heartbeat_repo=heartbeat_repo,
    )


def test_pipeline_tick_runs_fixed_non_ui_stages_with_one_now_and_batches() -> None:
    context = worker_fixture()

    result = context.worker.run_tick(NOW)

    assert context.order == [
        "group_clean",
        "group_analysis",
        "article_parse",
        "article_analysis",
    ]
    assert context.stages["group_clean"].calls == [(50, NOW)]
    assert context.stages["group_analysis"].calls == [(100, NOW)]
    assert context.stages["article_parse"].calls == [(20, NOW)]
    assert context.stages["article_analysis"].calls == [(20, NOW)]
    assert result.group_clean_success == 3
    assert result.group_analysis_success == 4
    assert result.article_parse_success == 5
    assert result.article_analysis_success == 2
    assert result.report_request_status is None


@pytest.mark.parametrize(
    "failed_stage",
    ["group_clean", "group_analysis", "article_parse", "article_analysis"],
)
def test_pipeline_tick_isolates_each_outer_stage_and_writes_safe_event(
    failed_stage: str,
) -> None:
    unsafe = RuntimeError(
        "https://secret.example/raw phone 13800138000\ntraceback body"
    )
    context = worker_fixture(stage_errors={failed_stage: unsafe})

    result = context.worker.run_tick(NOW)

    assert context.order == [
        "group_clean",
        "group_analysis",
        "article_parse",
        "article_analysis",
    ]
    assert getattr(result, f"{failed_stage}_success") == 0
    event = context.event_repo.events[0]
    assert event.stage == failed_stage
    assert event.event_type == "pipeline_stage_failed"
    assert json.loads(event.metrics_json) == {"exception_type": "RuntimeError"}
    assert "secret.example" not in event.message
    assert "13800138000" not in event.message
    assert "traceback" not in event.message.lower()
    assert "body" not in event.message.lower()
    assert event.job_id is None and event.run_id is None


def test_pipeline_tick_continues_when_failure_event_cannot_be_written() -> None:
    context = worker_fixture(
        stage_errors={"group_clean": RuntimeError("boom")},
        event_fail=True,
    )

    result = context.worker.run_tick(NOW)

    assert context.order[-1] == "article_analysis"
    assert result.group_clean_success == 0
    assert result.article_analysis_success == 2


def test_pipeline_tick_claims_and_executes_at_most_one_report_request() -> None:
    requests = [object(), object()]
    context = worker_fixture(report_requests=requests)

    result = context.worker.run_tick(NOW)

    assert context.report_repo.calls == [(NOW, "pipeline-test-1", 120)]
    assert context.report_service.execute_calls == [
        (requests[0], "pipeline-test-1", NOW)
    ]
    assert result.report_request_status == "partial_success"
    assert len(context.report_repo.requests) == 1


@pytest.mark.parametrize("failure_at", ["claim", "execute"])
def test_pipeline_tick_isolates_report_outer_failure(failure_at: str) -> None:
    context = worker_fixture(
        report_requests=[object()],
        report_repo_error=(RuntimeError("claim failed") if failure_at == "claim" else None),
        report_service_error=(RuntimeError("execute failed") if failure_at == "execute" else None),
    )

    result = context.worker.run_tick(NOW)

    assert result.report_request_status == "failed"
    assert context.event_repo.events[-1].stage == "report"
    assert context.event_repo.events[-1].event_type == "pipeline_stage_failed"


def test_pipeline_tick_can_reclaim_on_next_tick_after_execute_and_event_fail() -> None:
    restored_request = object()
    context = worker_fixture(
        report_requests=[restored_request, restored_request],
        report_service_error=RuntimeError("execute failed"),
        event_fail=True,
    )

    first = context.worker.run_tick(NOW)
    second = context.worker.run_tick(NOW)

    assert first.report_request_status == "failed"
    assert second.report_request_status == "failed"
    assert len(context.report_repo.calls) == 2
    assert context.report_service.execute_calls == [
        (restored_request, "pipeline-test-1", NOW),
        (restored_request, "pipeline-test-1", NOW),
    ]


def test_compensation_targets_previous_shanghai_calendar_date() -> None:
    context = worker_fixture()

    request_id = context.worker.ensure_daily_compensation(NOW)

    assert request_id == 73
    assert context.report_service.compensation_calls == [
        (date(2026, 7, 10), NOW)
    ]
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        context.worker.ensure_daily_compensation(NOW.replace(tzinfo=None))


def test_pipeline_heartbeat_and_shutdown_status_use_pipeline_type() -> None:
    context = worker_fixture()

    context.worker.heartbeat(NOW)
    context.worker.mark_stopping(NOW)
    context.worker.mark_stopped(NOW)

    records = context.heartbeat_repo.records
    assert [record.status for record in records] == [
        "running",
        "stopping",
        "stopped",
    ]
    assert all(record.worker_type == "pipeline" for record in records)
    assert all(record.worker_id == "pipeline-test-1" for record in records)


def test_pipeline_now_wrappers_use_injected_shanghai_clock() -> None:
    context = worker_fixture(now_provider=lambda: NOW)

    context.worker.run_tick_now()
    context.worker.heartbeat_now()
    context.worker.ensure_daily_compensation_now()

    assert context.stages["group_clean"].calls == [(50, NOW)]
    assert context.heartbeat_repo.records[-1].last_heartbeat_at == NOW
    assert context.report_service.compensation_calls[-1] == (
        date(2026, 7, 10),
        NOW,
    )


def test_scheduled_heartbeat_and_compensation_hide_errors_from_scheduler() -> None:
    unsafe = RuntimeError(
        "https://secret.example/raw 13800138000 traceback article body"
    )
    context = worker_fixture(
        heartbeat_error=unsafe,
        compensation_error=unsafe,
    )

    assert context.worker.heartbeat_now() is None
    assert context.worker.ensure_daily_compensation_now() is None

    assert [event.stage for event in context.event_repo.events] == [
        "heartbeat",
        "compensation",
    ]
    for event in context.event_repo.events:
        assert event.event_type == "pipeline_stage_failed"
        assert json.loads(event.metrics_json) == {
            "exception_type": "RuntimeError"
        }
        assert "secret.example" not in event.message
        assert "13800138000" not in event.message
        assert "traceback" not in event.message.lower()
        assert "body" not in event.message.lower()

    with pytest.raises(RuntimeError):
        context.worker.heartbeat(NOW)
    with pytest.raises(RuntimeError):
        context.worker.ensure_daily_compensation(NOW)


def test_scheduled_tick_hides_clock_error_and_returns_failed_result() -> None:
    unsafe = RuntimeError(
        "https://secret.example/raw 13800138000 traceback article body"
    )
    context = worker_fixture(
        now_provider=lambda: (_ for _ in ()).throw(unsafe),
    )

    result = context.worker.run_tick_now()

    assert result.group_clean_success == 0
    assert result.group_analysis_success == 0
    assert result.article_parse_success == 0
    assert result.article_analysis_success == 0
    assert result.report_request_status == "failed"
    event = context.event_repo.events[-1]
    assert event.stage == "tick"
    assert json.loads(event.metrics_json) == {"exception_type": "RuntimeError"}
    assert "secret.example" not in event.message
    assert "13800138000" not in event.message
    assert "traceback" not in event.message.lower()
    assert "body" not in event.message.lower()

    with pytest.raises(ValueError, match="Asia/Shanghai"):
        context.worker.run_tick(NOW.replace(tzinfo=None))


def _config():
    return SimpleNamespace(
        mysql=object(),
        workers=SimpleNamespace(
            heartbeat_seconds=10,
            pipeline_tick_seconds=5,
            run_lease_seconds=120,
            group_clean_batch_size=50,
            group_analysis_batch_size=100,
            article_parse_batch_size=20,
            article_analysis_batch_size=20,
        ),
        pipelines=SimpleNamespace(
            article=SimpleNamespace(
                rpa_timeout_seconds=30,
                browser_executable_path="auto",
                price_items_json_preview_limit=20,
                egg_price_extraction_enabled=True,
                image_quote_note_enabled=True,
            )
        ),
    )


def test_runtime_factory_wires_every_repo_to_one_shared_engine() -> None:
    engine = object()

    worker = build_pipeline_worker(
        _config(),
        engine=engine,
        worker_id="pipeline-test-1",
        hostname="host",
        process_id=7,
        now_provider=lambda: NOW,
    )

    assert worker.group_clean_service.repo.engine is engine
    assert worker.group_analysis_service.repo.engine is engine
    assert worker.article_parse_service.repo.engine is engine
    assert worker.article_analysis_service.repo.engine is engine
    assert worker.report_repo.engine is engine
    assert worker.event_repo.engine is engine
    assert worker.heartbeat_repo.engine is engine
    assert worker.report_service.group_report_service.repo.engine is engine
    assert worker.report_service.article_report_service.repo.engine is engine


class Scheduler:
    def __init__(self, *, timezone):
        self.timezone = timezone
        self.jobs = []
        self.started = False
        self.shutdown_calls = []

    def add_job(self, function, trigger, **kwargs):
        self.jobs.append((function, trigger, kwargs))

    def start(self):
        self.started = True

    def shutdown(self, *, wait):
        self.shutdown_calls.append(wait)


class MainWorker:
    def __init__(self):
        self.calls = []

    def run_tick_now(self):
        self.calls.append("tick")

    def heartbeat_now(self):
        self.calls.append("heartbeat")

    def ensure_daily_compensation_now(self):
        self.calls.append("compensation")

    def heartbeat(self, now):
        self.calls.append(("heartbeat", now))

    def mark_stopping(self, now):
        self.calls.append(("stopping", now))

    def mark_stopped(self, now):
        self.calls.append(("stopped", now))


def test_pipeline_main_registers_exact_three_blocking_scheduler_jobs(
    monkeypatch,
) -> None:
    config = _config()
    worker = MainWorker()
    schedulers = []
    monkeypatch.setattr(pipeline_main, "load_config", lambda path: config)

    def scheduler_factory(**kwargs):
        scheduler = Scheduler(**kwargs)
        schedulers.append(scheduler)
        return scheduler

    result = pipeline_main.main(
        ["--config", "safe.yaml"],
        runtime_builder=lambda selected: worker,
        scheduler_factory=scheduler_factory,
        now_provider=lambda: NOW,
    )

    assert result == 0
    scheduler = schedulers[0]
    assert scheduler.timezone == "Asia/Shanghai"
    assert scheduler.started is True
    assert [trigger for _, trigger, _ in scheduler.jobs] == [
        "interval",
        "interval",
        "cron",
    ]
    assert [kwargs for _, _, kwargs in scheduler.jobs] == [
        {"seconds": 5, "max_instances": 1, "coalesce": True},
        {"seconds": 10, "max_instances": 1, "coalesce": True},
        {"hour": 0, "minute": 10, "max_instances": 1, "coalesce": True},
    ]
    assert scheduler.shutdown_calls == [True]
    assert worker.calls[0] == ("heartbeat", NOW)
    assert worker.calls[1] == "compensation"
    assert worker.calls[-2:] == [("stopping", NOW), ("stopped", NOW)]


def test_pipeline_main_once_runs_one_tick_without_scheduler(monkeypatch) -> None:
    worker = MainWorker()
    monkeypatch.setattr(pipeline_main, "load_config", lambda path: _config())

    result = pipeline_main.main(
        ["--config", "safe.yaml", "--once"],
        runtime_builder=lambda selected: worker,
        scheduler_factory=lambda **kwargs: pytest.fail("scheduler not expected"),
        now_provider=lambda: NOW,
    )

    assert result == 0
    assert worker.calls == [
        ("heartbeat", NOW),
        "compensation",
        "tick",
        ("stopping", NOW),
        ("stopped", NOW),
    ]


def test_pipeline_main_waits_for_scheduler_before_marking_stopped(
    monkeypatch,
) -> None:
    worker = MainWorker()
    monkeypatch.setattr(pipeline_main, "load_config", lambda path: _config())

    class OrderedScheduler(Scheduler):
        def shutdown(self, *, wait):
            worker.calls.append(("scheduler_shutdown", wait))
            super().shutdown(wait=wait)

    result = pipeline_main.main(
        ["--config", "safe.yaml"],
        runtime_builder=lambda selected: worker,
        scheduler_factory=OrderedScheduler,
        now_provider=lambda: NOW,
    )

    assert result == 0
    assert worker.calls[-3:] == [
        ("stopping", NOW),
        ("scheduler_shutdown", True),
        ("stopped", NOW),
    ]


def test_pipeline_main_reports_safe_runtime_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pipeline_main, "load_config", lambda path: _config())

    result = pipeline_main.main(
        ["--config", "C:/secret/password.yaml"],
        runtime_builder=lambda selected: (_ for _ in ()).throw(
            RuntimeError("password=hunter2 C:/secret/password.yaml")
        ),
        now_provider=lambda: NOW,
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == "pipeline_runtime_error=RuntimeError"
    assert "hunter2" not in captured.err
    assert "password.yaml" not in captured.err


def test_pipeline_modules_have_no_ui_lock_or_real_rpa_dependency() -> None:
    from app.workers import pipeline_runtime_factory, pipeline_worker

    source = "\n".join(
        inspect.getsource(module)
        for module in (pipeline_worker, pipeline_runtime_factory, pipeline_main)
    ).lower()
    for forbidden in (
        "ui_lock",
        "mysqluilockrepo",
        "wxauto",
        "collect-group",
        "collect-article",
        "mark_success",
        "mark_partial_success",
        "mark_failed",
    ):
        assert forbidden not in source
