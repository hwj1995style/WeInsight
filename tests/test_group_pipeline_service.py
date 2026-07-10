from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.pipelines.group_pipeline_service import GroupPipelineService


@dataclass(frozen=True)
class FakeCollectResult:
    group_name: str
    batch_id: str
    read_count: int
    insert_count: int
    duplicate_count: int


@dataclass(frozen=True)
class FakeCountResult:
    read_count: int
    success_count: int
    failed_count: int


@dataclass(frozen=True)
class FakeReportResult:
    report_date: date
    generated_count: int


class FakeCollectService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime]] = []

    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime) -> FakeCollectResult:
        self.calls.append((group_name, batch_id, collect_time))
        return FakeCollectResult(group_name=group_name, batch_id=batch_id, read_count=2, insert_count=1, duplicate_count=1)


class FakeCleanService:
    def __init__(self, result: FakeCountResult) -> None:
        self.result = result
        self.calls: list[tuple[int, datetime]] = []

    def clean_once(self, limit: int, clean_time: datetime) -> FakeCountResult:
        self.calls.append((limit, clean_time))
        return self.result


class FakeAnalysisService:
    def __init__(self, result: FakeCountResult) -> None:
        self.result = result
        self.calls: list[tuple[int, datetime]] = []

    def analyze_once(self, limit: int, analyze_time: datetime) -> FakeCountResult:
        self.calls.append((limit, analyze_time))
        return self.result


class FakeDailyReportService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, str | None, datetime]] = []

    def generate_once(self, report_date: date, group_name: str | None, generate_time: datetime) -> FakeReportResult:
        self.calls.append((report_date, group_name, generate_time))
        return FakeReportResult(report_date=report_date, generated_count=1)


def _service(
    *,
    clean_result: FakeCountResult = FakeCountResult(0, 0, 0),
    analysis_result: FakeCountResult = FakeCountResult(0, 0, 0),
) -> tuple[GroupPipelineService, FakeCollectService, FakeCleanService, FakeAnalysisService, FakeDailyReportService]:
    collect = FakeCollectService()
    clean = FakeCleanService(clean_result)
    analysis = FakeAnalysisService(analysis_result)
    report = FakeDailyReportService()
    return (
        GroupPipelineService(
            collect_service=collect,
            clean_service=clean,
            analysis_service=analysis,
            daily_report_service=report,
        ),
        collect,
        clean,
        analysis,
        report,
    )


def test_group_pipeline_service_skip_collect_runs_postprocess_stages() -> None:
    service, collect, clean, analysis, report = _service(
        clean_result=FakeCountResult(2, 2, 0),
        analysis_result=FakeCountResult(2, 2, 0),
    )
    now = datetime(2026, 7, 3, 12, 0, 0)

    result = service.run_once(
        report_date=date(2026, 7, 3),
        group_name=None,
        skip_collect=True,
        limit=20,
        run_time=now,
        batch_id="pipeline-1",
    )

    assert result.status == "success"
    assert [stage.stage for stage in result.stages] == ["collect", "clean", "analyze", "report"]
    assert result.stages[0].status == "skipped"
    assert collect.calls == []
    assert clean.calls == [(20, now)]
    assert analysis.calls == [(20, now)]
    assert report.calls == [(date(2026, 7, 3), None, now)]


def test_group_pipeline_service_collects_single_explicit_group_before_postprocess() -> None:
    service, collect, clean, analysis, report = _service(
        clean_result=FakeCountResult(1, 1, 0),
        analysis_result=FakeCountResult(1, 1, 0),
    )
    now = datetime(2026, 7, 3, 12, 0, 0)

    result = service.run_once(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        skip_collect=False,
        limit=20,
        run_time=now,
        batch_id="pipeline-1",
    )

    assert result.status == "success"
    assert collect.calls == [("核心群A", "pipeline-1", now)]
    assert report.calls == [(date(2026, 7, 3), "核心群A", now)]
    assert result.stages[0].metrics["insert_count"] == 1


def test_group_pipeline_service_stops_after_clean_failure() -> None:
    service, collect, clean, analysis, report = _service(
        clean_result=FakeCountResult(2, 1, 1),
        analysis_result=FakeCountResult(2, 2, 0),
    )

    result = service.run_once(
        report_date=date(2026, 7, 3),
        group_name=None,
        skip_collect=True,
        limit=20,
        run_time=datetime(2026, 7, 3, 12, 0, 0),
        batch_id="pipeline-1",
    )

    assert result.status == "failed"
    assert result.failed_stage == "clean"
    assert [stage.stage for stage in result.stages] == ["collect", "clean"]
    assert analysis.calls == []
    assert report.calls == []


def test_group_pipeline_service_stops_after_analyze_failure() -> None:
    service, collect, clean, analysis, report = _service(
        clean_result=FakeCountResult(2, 2, 0),
        analysis_result=FakeCountResult(2, 1, 1),
    )

    result = service.run_once(
        report_date=date(2026, 7, 3),
        group_name=None,
        skip_collect=True,
        limit=20,
        run_time=datetime(2026, 7, 3, 12, 0, 0),
        batch_id="pipeline-1",
    )

    assert result.status == "failed"
    assert result.failed_stage == "analyze"
    assert [stage.stage for stage in result.stages] == ["collect", "clean", "analyze"]
    assert report.calls == []
