from app.content.fallback_provider import FallbackArticleContentProvider
from app.workers.pipeline_runtime_factory import build_article_content_provider


class ArticleConfig:
    content_base_url = "http://127.0.0.1:8001"
    content_timeout_seconds = 30
    content_max_response_bytes = 5242880
    content_mode = "werss_first"
    browser_executable_path = "auto"


def test_werss_first_builds_fallback_provider():
    assert isinstance(build_article_content_provider(ArticleConfig()), FallbackArticleContentProvider)
