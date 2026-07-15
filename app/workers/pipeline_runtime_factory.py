from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.engine import Engine

from app.core.config import Config
from app.content.article_content import ProcessShadowMetrics, ShadowArticleContentProvider
from app.content.fallback_provider import FallbackArticleContentProvider
from app.content.werss_provider import WeRSSContentProvider
from app.pipelines.article_analysis_service import ArticleAnalysisService
from app.pipelines.article_daily_report_service import ArticleDailyReportService
from app.pipelines.article_parse_service import (
    ArticleParseService,
    PlaywrightArticleContentProvider,
)
from app.pipelines.article_transient_extractor import (
    PlaywrightArticleTransientExtractor,
    ProviderBackedArticleTransientExtractor,
    TextFirstArticleTransientExtractor,
)
from app.pipelines.group_analysis_service import (
    GroupAnalysisService,
    GroupDailyReportService,
)
from app.pipelines.group_clean_service import GroupCleanService
from app.pipelines.summary_daily_report_query_service import (
    SummaryDailyReportQueryService,
)
from app.pipelines.summary_daily_report_service import SummaryDailyReportService
from app.services.report_generation_service import ReportGenerationService
from app.services.windows_ocr_service import WindowsOcrService
from app.services.event_retention_service import EventRetentionPolicy, EventRetentionService
from app.storage.article_analysis_repo import MysqlArticleAnalysisRepo
from app.storage.article_daily_report_repo import MysqlArticleDailyReportRepo
from app.storage.article_parse_repo import MysqlArticleParseRepo
from app.storage.collection_event_repo import MysqlCollectionEventRepo
from app.storage.db import create_mysql_engine
from app.storage.group_analysis_repo import MysqlGroupAnalysisRepo
from app.storage.group_clean_repo import MysqlGroupCleanRepo
from app.storage.report_request_repo import MysqlReportRequestRepo
from app.storage.summary_daily_report_query_repo import (
    MysqlSummaryDailyReportQueryRepo,
)
from app.storage.worker_heartbeat_repo import MysqlWorkerHeartbeatRepo
from app.storage.event_retention_repo import MysqlEventRetentionRepo
from app.workers.pipeline_worker import (
    PipelineWorker,
    default_pipeline_worker_identity,
)


_ARTICLE_CONTENT_SHADOW_METRICS = ProcessShadowMetrics()


def build_pipeline_worker(
    config: Config,
    *,
    engine: Engine | None = None,
    worker_id: str | None = None,
    hostname: str | None = None,
    process_id: int | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> PipelineWorker:
    shared_engine = engine or create_mysql_engine(config.mysql)
    identity = default_pipeline_worker_identity()
    selected_worker_id = worker_id or identity[0]
    selected_hostname = hostname or identity[1]
    selected_process_id = process_id or identity[2]
    clock = now_provider

    group_clean_repo = MysqlGroupCleanRepo(shared_engine)
    group_analysis_repo = MysqlGroupAnalysisRepo(shared_engine)
    article_parse_repo = MysqlArticleParseRepo(shared_engine)
    article_analysis_repo = MysqlArticleAnalysisRepo(shared_engine)
    article_daily_report_repo = MysqlArticleDailyReportRepo(shared_engine)
    summary_repo = MysqlSummaryDailyReportQueryRepo(shared_engine)
    report_repo = MysqlReportRequestRepo(shared_engine)

    group_clean_service = GroupCleanService(repo=group_clean_repo)
    group_analysis_service = GroupAnalysisService(repo=group_analysis_repo)
    article_parse_service = ArticleParseService(
        repo=article_parse_repo,
        provider=build_article_content_provider(config.pipelines.article),
    )
    article_analysis_service = ArticleAnalysisService(
        repo=article_analysis_repo,
        extractor=build_article_transient_extractor(config.pipelines.article),
        price_items_preview_limit=(
            config.pipelines.article.price_items_json_preview_limit
        ),
        egg_price_extraction_enabled=(
            config.pipelines.article.egg_price_extraction_enabled
        ),
    )
    report_service = ReportGenerationService(
        repo=report_repo,
        group_report_service=GroupDailyReportService(
            repo=group_analysis_repo
        ),
        article_report_service=ArticleDailyReportService(
            repo=article_daily_report_repo
        ),
        summary_report_service=SummaryDailyReportService(
            query_service=SummaryDailyReportQueryService(repo=summary_repo)
        ),
    )
    start_time = clock() if clock is not None else _shanghai_now()
    return PipelineWorker(
        group_clean_service=group_clean_service,
        group_analysis_service=group_analysis_service,
        article_parse_service=article_parse_service,
        article_analysis_service=article_analysis_service,
        report_repo=report_repo,
        report_service=report_service,
        event_repo=MysqlCollectionEventRepo(shared_engine),
        heartbeat_repo=MysqlWorkerHeartbeatRepo(shared_engine),
        worker_id=selected_worker_id,
        hostname=selected_hostname,
        process_id=selected_process_id,
        version="pipeline-worker-v1",
        start_time=start_time,
        report_lease_seconds=config.workers.run_lease_seconds,
        group_clean_batch_size=config.workers.group_clean_batch_size,
        group_analysis_batch_size=config.workers.group_analysis_batch_size,
        article_parse_batch_size=config.workers.article_parse_batch_size,
        article_analysis_batch_size=(
            config.workers.article_analysis_batch_size
        ),
        now_provider=clock,
        event_retention_service=EventRetentionService(
            MysqlEventRetentionRepo(shared_engine),
            EventRetentionPolicy(
                info_days=getattr(config.workers, "event_info_retention_days", 14),
                verbose_days=getattr(config.workers, "event_verbose_retention_days", 7),
                warning_error_months=getattr(config.workers, "event_warning_error_retention_months", 3),
                audit_months=getattr(config.workers, "event_audit_retention_months", 6),
                batch_size=getattr(config.workers, "event_cleanup_batch_size", 1000),
            ),
        ),
    )


def _shanghai_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai"))


def build_article_content_provider(article_config):
    timeout_seconds = getattr(article_config, "content_timeout_seconds", 30)
    content_mode = getattr(article_config, "content_mode", "web")
    web = PlaywrightArticleContentProvider(
        timeout_ms=timeout_seconds * 1000,
        browser_executable_path=article_config.browser_executable_path,
    )
    if content_mode == "web":
        return web
    werss = WeRSSContentProvider(
        endpoint=getattr(article_config, "content_base_url", "http://127.0.0.1:8001"),
        timeout_seconds=timeout_seconds,
        max_response_bytes=getattr(article_config, "content_max_response_bytes", 5_242_880),
    )
    if content_mode == "shadow":
        return ShadowArticleContentProvider(
            web, werss, _ARTICLE_CONTENT_SHADOW_METRICS
        )
    return FallbackArticleContentProvider(werss, web)


def build_article_transient_extractor(article_config):
    provider_extractor = ProviderBackedArticleTransientExtractor(
        build_article_content_provider(article_config)
    )
    ocr_engine = (
        WindowsOcrService(
            timeout_seconds=getattr(article_config, "content_timeout_seconds", 30)
        )
        if getattr(article_config, "image_ocr_enabled", True)
        else None
    )
    dom_extractor = PlaywrightArticleTransientExtractor(
        timeout_ms=getattr(article_config, "content_timeout_seconds", 30) * 1000,
        browser_executable_path=article_config.browser_executable_path,
        image_quote_note_enabled=getattr(
            article_config, "image_quote_note_enabled", True
        ),
        ocr_engine=ocr_engine,
    )
    return TextFirstArticleTransientExtractor(provider_extractor, dom_extractor)


def get_article_content_shadow_metrics() -> dict[str, int]:
    return _ARTICLE_CONTENT_SHADOW_METRICS.snapshot()
