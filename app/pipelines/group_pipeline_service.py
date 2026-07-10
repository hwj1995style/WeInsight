from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class PipelineStageResult:
    stage: str
    status: str
    metrics: dict[str, int | str]
    error_msg: str | None = None


@dataclass(frozen=True)
class GroupPipelineResult:
    status: str
    failed_stage: str | None
    error_msg: str | None
    stages: list[PipelineStageResult]


class GroupPipelineCollectService(Protocol):
    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime):
        ...


class GroupPipelineCleanService(Protocol):
    def clean_once(self, limit: int, clean_time: datetime):
        ...


class GroupPipelineAnalysisService(Protocol):
    def analyze_once(self, limit: int, analyze_time: datetime):
        ...


class GroupPipelineDailyReportService(Protocol):
    def generate_once(self, report_date: date, group_name: str | None, generate_time: datetime):
        ...


class GroupPipelineService:
    def __init__(
        self,
        *,
        collect_service: GroupPipelineCollectService,
        clean_service: GroupPipelineCleanService,
        analysis_service: GroupPipelineAnalysisService,
        daily_report_service: GroupPipelineDailyReportService,
    ) -> None:
        self.collect_service = collect_service
        self.clean_service = clean_service
        self.analysis_service = analysis_service
        self.daily_report_service = daily_report_service

    def run_once(
        self,
        *,
        report_date: date,
        group_name: str | None,
        skip_collect: bool,
        limit: int,
        run_time: datetime,
        batch_id: str,
    ) -> GroupPipelineResult:
        stages: list[PipelineStageResult] = []

        if skip_collect:
            stages.append(PipelineStageResult(stage="collect", status="skipped", metrics={}))
        else:
            if not group_name:
                return _failed_result(
                    stages,
                    "collect",
                    "group_name is required when collect stage is enabled",
                )
            try:
                collect_result = self.collect_service.collect_once(
                    group_name=group_name,
                    batch_id=batch_id,
                    collect_time=run_time,
                )
                stages.append(
                    PipelineStageResult(
                        stage="collect",
                        status="success",
                        metrics={
                            "read_count": int(collect_result.read_count),
                            "insert_count": int(collect_result.insert_count),
                            "duplicate_count": int(collect_result.duplicate_count),
                        },
                    )
                )
            except Exception as exc:
                return _failed_result(stages, "collect", str(exc))

        clean_result = self.clean_service.clean_once(limit=limit, clean_time=run_time)
        clean_stage = _count_stage("clean", clean_result)
        stages.append(clean_stage)
        if clean_stage.status == "failed":
            return _result("failed", stages, "clean", "clean failed_count>0")

        analysis_result = self.analysis_service.analyze_once(limit=limit, analyze_time=run_time)
        analysis_stage = _count_stage("analyze", analysis_result)
        stages.append(analysis_stage)
        if analysis_stage.status == "failed":
            return _result("failed", stages, "analyze", "analyze failed_count>0")

        try:
            report_result = self.daily_report_service.generate_once(
                report_date=report_date,
                group_name=group_name,
                generate_time=run_time,
            )
            stages.append(
                PipelineStageResult(
                    stage="report",
                    status="success",
                    metrics={"generated_count": int(report_result.generated_count)},
                )
            )
        except Exception as exc:
            return _failed_result(stages, "report", str(exc))

        return _result("success", stages, None, None)


def _count_stage(stage: str, result) -> PipelineStageResult:
    failed_count = int(result.failed_count)
    return PipelineStageResult(
        stage=stage,
        status="failed" if failed_count > 0 else "success",
        metrics={
            "read_count": int(result.read_count),
            "success_count": int(result.success_count),
            "failed_count": failed_count,
        },
    )


def _failed_result(stages: list[PipelineStageResult], failed_stage: str, error_msg: str) -> GroupPipelineResult:
    stages.append(PipelineStageResult(stage=failed_stage, status="failed", metrics={}, error_msg=error_msg))
    return _result("failed", stages, failed_stage, error_msg)


def _result(
    status: str,
    stages: list[PipelineStageResult],
    failed_stage: str | None,
    error_msg: str | None,
) -> GroupPipelineResult:
    return GroupPipelineResult(
        status=status,
        failed_stage=failed_stage,
        error_msg=error_msg,
        stages=stages,
    )
