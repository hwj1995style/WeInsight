from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import Config
from app.security.passwords import PasswordHasher
from app.services.auth_service import AuthService
from app.services.article_source_status_service import ArticleSourceStatusService
from app.services.article_downstream_service import ArticleDownstreamService
from app.services.dashboard_service import DashboardService
from app.services.collection_job_service import CollectionJobService
from app.services.result_query_service import ResultQueryService
from app.services.source_management_service import SourceManagementService
from app.services.report_generation_service import ReportGenerationService
from app.services.werss_authorization_factory import build_werss_authorization_service
from app.storage.admin_auth_repo import MysqlAdminAuthRepo
from app.storage.article_config_repo import MysqlArticleAccountConfigRepo
from app.storage.article_source_status_repo import MysqlArticleSourceStatusRepo
from app.storage.article_downstream_repo import MysqlArticleDownstreamRepo
from app.storage.article_daily_report_query_repo import MysqlArticleDailyReportQueryRepo
from app.storage.db import create_mysql_engine
from app.storage.dashboard_repo import MysqlDashboardRepo
from app.storage.collection_job_repo import MysqlCollectionJobRepo
from app.storage.collection_event_repo import MysqlCollectionEventRepo
from app.storage.group_repo import MysqlGroupConfigRepo
from app.storage.group_daily_report_query_repo import MysqlGroupDailyReportQueryRepo
from app.storage.safe_result_query_repo import MysqlSafeResultQueryRepo
from app.storage.source_reference_repo import MysqlSourceReferenceRepo
from app.storage.summary_daily_report_query_repo import MysqlSummaryDailyReportQueryRepo
from app.storage.report_request_repo import MysqlReportRequestRepo
from app.storage.group_analysis_repo import MysqlGroupAnalysisRepo
from app.storage.article_daily_report_repo import MysqlArticleDailyReportRepo
from app.pipelines.group_analysis_service import GroupDailyReportService
from app.pipelines.article_daily_report_service import ArticleDailyReportService
from app.pipelines.summary_daily_report_service import SummaryDailyReportService
from app.pipelines.article_daily_report_query_service import ArticleDailyReportQueryService
from app.pipelines.group_daily_report_query_service import GroupDailyReportQueryService
from app.pipelines.summary_daily_report_query_service import SummaryDailyReportQueryService
from app.web.middleware import AdminSessionMiddleware
from app.web.routes import (
    auth,
    dashboard,
    events,
    jobs,
    reports,
    results,
    runs,
    sources,
    workers,
)
from app.web.routes.auth import LoginAttemptLimiter, MAX_CONCURRENT_LOGIN_HASHES

if TYPE_CHECKING:
    from app.services.runtime_monitor_service import RuntimeMonitorService


WEB_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.login_hash_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOGIN_HASHES)
    try:
        yield
    finally:
        app.state.login_hash_semaphore = None


def create_app(
    config: Config,
    auth_service: AuthService | None = None,
    source_service: SourceManagementService | None = None,
    article_status_service: ArticleSourceStatusService | None = None,
    article_downstream_service: ArticleDownstreamService | None = None,
    result_service: ResultQueryService | None = None,
    group_report_service: GroupDailyReportQueryService | None = None,
    article_report_service: ArticleDailyReportQueryService | None = None,
    summary_report_service: SummaryDailyReportQueryService | None = None,
    dashboard_service: DashboardService | None = None,
    job_service: CollectionJobService | None = None,
    runtime_monitor_service: "RuntimeMonitorService | None" = None,
    event_repo: MysqlCollectionEventRepo | None = None,
    report_request_service: ReportGenerationService | None = None,
    report_request_repo: MysqlReportRequestRepo | None = None,
    werss_authorization_service=None,
) -> FastAPI:
    app = FastAPI(
        title="WeInsight Admin",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.config = config
    app.state.article_downstream_flashes = OrderedDict()
    engine = None
    if any(
        service is None
        for service in (
            auth_service,
            source_service,
            article_status_service,
            article_downstream_service,
            result_service,
            group_report_service,
            article_report_service,
            summary_report_service,
            dashboard_service,
            job_service,
            runtime_monitor_service,
            event_repo,
            report_request_service,
            report_request_repo,
            werss_authorization_service,
        )
    ):
        engine = create_mysql_engine(config.mysql)
    app.state.auth_service = auth_service or _build_auth_service(config, engine)
    app.state.source_service = source_service or _build_source_service(engine)
    app.state.article_status_service = article_status_service or ArticleSourceStatusService(
        MysqlArticleSourceStatusRepo(engine), config.pipelines.article.sync_interval_minutes
    )
    app.state.article_downstream_service = article_downstream_service or ArticleDownstreamService(
        MysqlArticleDownstreamRepo(engine)
    )
    app.state.result_service = result_service or ResultQueryService(
        MysqlSafeResultQueryRepo(engine)
    )
    app.state.group_report_service = group_report_service or GroupDailyReportQueryService(
        repo=MysqlGroupDailyReportQueryRepo(engine)
    )
    app.state.article_report_service = (
        article_report_service
        or ArticleDailyReportQueryService(repo=MysqlArticleDailyReportQueryRepo(engine))
    )
    app.state.summary_report_service = (
        summary_report_service
        or SummaryDailyReportQueryService(repo=MysqlSummaryDailyReportQueryRepo(engine))
    )
    app.state.report_request_repo = (
        report_request_repo or MysqlReportRequestRepo(engine)
    )
    app.state.report_request_service = (
        report_request_service
        or ReportGenerationService(
            repo=app.state.report_request_repo,
            group_report_service=GroupDailyReportService(
                repo=MysqlGroupAnalysisRepo(engine)
            ),
            article_report_service=ArticleDailyReportService(
                repo=MysqlArticleDailyReportRepo(engine)
            ),
            summary_report_service=SummaryDailyReportService(
                query_service=app.state.summary_report_service
            ),
        )
    )
    app.state.dashboard_service = dashboard_service or DashboardService(
        MysqlDashboardRepo(engine)
    )
    app.state.job_service = job_service or CollectionJobService(
        MysqlCollectionJobRepo(engine)
    )
    if runtime_monitor_service is None:
        from app.services.runtime_monitor_service import RuntimeMonitorService
        from app.storage.runtime_monitor_repo import MysqlRuntimeMonitorRepo

        runtime_monitor_service = RuntimeMonitorService(
            MysqlRuntimeMonitorRepo(engine),
            Path(config.runtime.screenshot_dir),
            heartbeat_ttl_seconds=config.workers.heartbeat_seconds * 3,
        )
    app.state.runtime_monitor_service = runtime_monitor_service
    app.state.event_repo = event_repo or MysqlCollectionEventRepo(engine)
    app.state.werss_authorization_service = (
        werss_authorization_service
        or build_werss_authorization_service(config, engine)
    )
    app.state.login_attempt_limiter = LoginAttemptLimiter(
        config.auth.login_failure_limit,
        config.auth.login_lock_minutes,
    )
    app.add_middleware(AdminSessionMiddleware)
    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )
    app.include_router(auth.router)
    app.include_router(sources.router)
    app.include_router(jobs.router)
    app.include_router(runs.router)
    app.include_router(events.router)
    app.include_router(workers.router)
    app.include_router(results.router)
    app.include_router(reports.router)
    app.include_router(dashboard.router)
    return app


def _build_auth_service(config: Config, engine) -> AuthService:
    return AuthService(
        MysqlAdminAuthRepo(engine),
        PasswordHasher(),
        config.auth,
    )


def _build_source_service(engine) -> SourceManagementService:
    return SourceManagementService(
        MysqlGroupConfigRepo(engine),
        MysqlArticleAccountConfigRepo(engine),
        MysqlSourceReferenceRepo(engine),
    )
