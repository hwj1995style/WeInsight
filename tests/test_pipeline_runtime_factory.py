from pathlib import Path

from sqlalchemy import create_engine

from app.content.article_content import ArticleContent, ContentFetchError, ProcessShadowMetrics, ShadowArticleContentProvider
from app.content.fallback_provider import FallbackArticleContentProvider
from app.core.config import load_config
from app.pipelines.article_transient_extractor import ProviderBackedArticleTransientExtractor
from app.workers.pipeline_runtime_factory import build_article_content_provider, build_pipeline_worker, get_article_content_shadow_metrics


class ArticleConfig:
    content_base_url = "http://127.0.0.1:8001"
    content_timeout_seconds = 30
    content_max_response_bytes = 5242880
    content_mode = "werss_first"
    browser_executable_path = "auto"


def test_werss_first_builds_fallback_provider():
    provider = build_article_content_provider(ArticleConfig())
    assert isinstance(provider, FallbackArticleContentProvider)
    assert provider.primary.__class__.__name__ == "WeRSSContentProvider"
    assert provider.fallback.__class__.__name__ == "PlaywrightArticleContentProvider"


def test_parse_and_analysis_shadow_providers_share_readable_process_metrics():
    config = ArticleConfig()
    config.content_mode = "shadow"
    first = build_article_content_provider(config)
    second = build_article_content_provider(config)
    assert isinstance(first, ShadowArticleContentProvider)
    assert isinstance(second, ShadowArticleContentProvider)
    assert first is not second
    assert first.metrics is second.metrics
    assert isinstance(first.metrics, ProcessShadowMetrics)
    assert get_article_content_shadow_metrics() == first.metrics.snapshot()


def test_werss_first_falls_back_only_for_recoverable_content_error():
    calls = []

    class Primary:
        def __init__(self, recoverable): self.recoverable = recoverable
        def parse(self, source):
            calls.append("werss")
            raise ContentFetchError("failed", self.recoverable)

    class Fallback:
        def parse(self, source):
            calls.append("web")
            return ArticleContent("body", None, None, None, None, "web")

    assert FallbackArticleContentProvider(Primary(True), Fallback()).parse(None).source == "web"
    assert calls == ["werss", "web"]
    calls.clear()
    try:
        FallbackArticleContentProvider(Primary(False), Fallback()).parse(None)
    except ContentFetchError:
        pass
    assert calls == ["werss"]


def test_pipeline_worker_wires_distinct_parse_and_analysis_providers_with_shared_metrics():
    worker = build_pipeline_worker(
        load_config(Path("config/config.dev.yaml")), engine=create_engine("sqlite://"),
        worker_id="w", hostname="h", process_id=1,
    )
    parse_provider = worker.article_parse_service.provider
    extractor = worker.article_analysis_service.extractor
    assert isinstance(extractor, ProviderBackedArticleTransientExtractor)
    assert parse_provider is not extractor.provider
    assert parse_provider.metrics is extractor.provider.metrics
